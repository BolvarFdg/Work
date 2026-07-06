positions正常说明问题在 **RoPE执行本身**。`NPUPlatform` 是 `PlatformEnum.OOT`，dispatch应该走 `forward_oot`。但 `get_rope()` 返回的是基类 `RotaryEmbedding`（`__init__.py:136`），而非 `AscendRotaryEmbedding`，所以 `forward_oot` 走的是 `CustomOp` 默认的 `forward_native` → `forward_static`（纯PyTorch实现），可能存在NPU上的兼容问题。

---

### 快速验证

在 `patch_qwen3_dflash.py:87` 前加：

```python
rotary = self.layers[0].self_attn.rotary_emb
print(f"rotary type={type(rotary).__name__}, "
      f"method={rotary._forward_method.__name__}, "
      f"head_size={rotary.head_size}, rotary_dim={rotary.rotary_dim}, "
      f"cos_sin_cache device={rotary.cos_sin_cache.device}, "
      f"cos_sin_cache shape={rotary.cos_sin_cache.shape}, "
      f"cos_sin_cache[0]={rotary.cos_sin_cache[0][:4].tolist()}")  # 应为[1.0, 0.0, ...]

# 手动测试forward_static是否工作
import torch
cos_sin = rotary.cos_sin_cache.to(all_k_flat_input.device).to(all_k_flat_input.dtype)
cos_sin_sel = cos_sin.index_select(0, positions_repeated[:8])
print(f"cos_sin_sel[:4]={cos_sin_sel[0][:4].tolist()}")  # 应不为[1.0, 0.0]如果positions>0
```

关键看：
- `cos_sin_cache[0]` 是否为 `[1.0, 0.0, 1.0, 0.0, ...]`（position 0的cos/sin）
- `cos_sin_sel` 对应你的positions是否不为 `[1.0, 0.0, ...]`
- `cos_sin_cache` 的 device 是否和 K tensor 一致

---

### 快速修复（绕过rotary_emb模块，直接调NPU算子）

如果确认是 `forward_static` 在NPU上失效，替换 `patch_qwen3_dflash.py:87-90`：

```python
# 替换原来的 rotary_emb 调用
from vllm_ascend.ops.rotary_embedding import rope_forward_oot

rotary = self.layers[0].self_attn.rotary_emb
cos_sin_cache = rotary.cos_sin_cache
if cos_sin_cache.dtype != all_k_flat_input.dtype:
    cos_sin_cache = cos_sin_cache.to(dtype=all_k_flat_input.dtype)
if cos_sin_cache.device != all_k_flat_input.device:
    cos_sin_cache = cos_sin_cache.to(device=all_k_flat_input.device)

all_k_flat, _ = rope_forward_oot(
    positions_repeated,
    all_k_flat_input,
    all_k_flat_input.clone(),
    cos_sin_cache,
    rotary.head_size,
    rotary.rotary_dim,
    rotary.is_neox_style,
)
```

`rope_forward_oot` 直接调用 `torch_npu._npu_rotary_embedding`（`rotary_embedding.py:189-212`），是NPU原生in-place算子，不经过CustomOp dispatch。