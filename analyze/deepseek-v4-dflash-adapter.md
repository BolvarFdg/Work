好的！问题根因是大模型用了 W8A8 量化版本，而小模型是在非量化版本上训练的，导致 hidden states 表示不匹配。

下面是所有**功能性修改**（排除诊断日志）的完整总结：

---

## 修改文件清单（7 个文件）

### 1. `vllm_ascend/models/deepseek_v4.py` — DeepSeek-V4 模型支持 aux hidden states

**目标**：让 DeepSeek-V4 实现 `SupportsEagle3` 接口，能收集 aux hidden states 供 DFlash drafter 使用。

**修改点**：

1. **导入** `SupportsEagle3` 和 `EagleModelMixin`：
```python
from vllm.model_executor.models.interfaces import (
    MixtureOfExperts, SupportsEagle, SupportsEagle3, SupportsLoRA, SupportsPP, EagleModelMixin
)
```

2. **`DeepseekV4Model`** 继承 `EagleModelMixin`，保持 `@support_torch_compile`：
```python
@support_torch_compile
class DeepseekV4Model(nn.Module, EagleModelMixin):
```
`EagleModelMixin` 提供 `aux_hidden_state_layers` 属性和 `_maybe_add_hidden_state` 方法。

3. **覆写 `_maybe_add_hidden_state`**：DeepSeek-V4 的 `hc_post` 已经将 residual 合并到 `hidden_states` 中，不能像标准 transformer 那样再加 `residual`（会双重叠加）：
```python
def _maybe_add_hidden_state(self, aux_hidden_states, layer_idx, hidden_states, residual):
    if layer_idx in self.aux_hidden_state_layers:
        aux_hidden_states.append(hidden_states)  # 不加 residual
    return aux_hidden_states
```

4. **`forward()` 收集 aux hidden states**：在层循环中调用 `_maybe_add_hidden_state`，当 `aux_hidden_state_layers` 非空时返回 `(hidden_states, aux_hidden_states)` 元组：
```python
aux_hidden_states: list[torch.Tensor] = []
for idx, layer in enumerate(islice(self.layers, ...), start=self.start_layer):
    self._maybe_add_hidden_state(aux_hidden_states, idx, hidden_states, residual)
    hidden_states, residual = layer(...)
...
if len(aux_hidden_states) > 0:
    return hidden_states, aux_hidden_states
return hidden_states
```

5. **`AscendDeepseekV4ForCausalLM`** 继承 `SupportsEagle3`，添加委托方法：
```python
class AscendDeepseekV4ForCausalLM(nn.Module, SupportsPP, ..., SupportsEagle, SupportsEagle3):
    def set_aux_hidden_state_layers(self, layers):
        self.model._set_aux_hidden_state_layers(layers)

    def get_eagle3_default_aux_hidden_state_layers(self):
        num_layers = len(self.model.layers)
        return (2, num_layers // 2, num_layers - 3)
```

---

### 2. `vllm_ascend/worker/model_runner_v1.py` — 运行时配置和 KV cache 适配

**目标**：为 DFlash 启用 aux hidden states，并解决 DeepSeek-V4 特有的 KV cache 分配/绑定问题。

**修改点**：

1. **为 dflash 设置 `use_aux_hidden_state_outputs`**（上游 GPU runner 已有此逻辑，Ascend 缺失）：
```python
elif self.speculative_config.method == "dflash":
    assert isinstance(self.drafter, AscendDflashProposer)
    self.use_aux_hidden_state_outputs = self.drafter.eagle3_use_aux_hidden_state
```

2. **当 `use_aux_hidden_state_outputs=True` 时跳过 `get_mtp_target_hidden_states()`**：aux hidden states 来自 `aux_hidden_states`，不需要 MTP 的 pre-hc_head residual：
```python
if not self.use_aux_hidden_state_outputs:
    mtp_hidden_states = getattr(
        self.get_model(), "get_mtp_target_hidden_states", lambda: None
    )()
    if mtp_hidden_states is not None:
        hidden_states = mtp_hidden_states
```

3. **aux hidden states 拼接时 flatten 3D→2D**（4 处）：DeepSeek-V4 的 aux hidden states 是 3D `(num_tokens, hc_mult, hidden_size)`，需要展平为 2D 供 drafter 的 `fc` 层使用：
```python
target_hidden_states = torch.cat(
    [h.flatten(1) if h.dim() > 2 else h for h in aux_hidden_states], dim=-1
)
```

4. **`_MlaSafeConfigProxy` 类**：轻量代理，覆盖 `model_config` 使 `use_mla=False`，其他属性代理到原始 config：
```python
class _MlaSafeConfigProxy:
    __slots__ = ("_base", "model_config")
    def __init__(self, base, draft_model_config):
        self._base = base
        self.model_config = draft_model_config
    def __getattr__(self, name):
        return getattr(self._base, name)
```

5. **`get_kv_cache_spec` 中使用 proxy**：DFlash draft 层有 `sliding_window`，DeepSeek-V4 的 `use_mla=True` 会触发 `assert not use_mla`。对 draft 层使用 proxy（`use_mla=False`）：
```python
if isinstance(attn_module, Attention) and attn_module.sliding_window is not None and draft_mc is not None:
    cfg = _MlaSafeConfigProxy(self.vllm_config, draft_mc)
```

6. **`_allocate_kv_cache_tensors` 修复**：原条件 `"attn" in layer_name and self.use_compress` 将 draft 层误分配为压缩单张量。添加 spec 类型检查，只对 MLA/SWA-MLA 层走压缩路径：
```python
elif "attn" in layer_name and self.use_compress and isinstance(
    layer_kv_cache_spec.get(layer_name), (MLAAttentionSpec, SlidingWindowMLASpec)
) and layer_name not in kv_cache_raw_tensors:
```

7. **`initialize_kv_cache_tensors` 绑定修复**：DeepSeek-V4 的绑定代码用 `[kv_cache]` 包裹，但标准 attention 的 `kv_cache` 是元组 `(k_cache, v_cache)`，包裹后变成 `[(k_cache, v_cache)]`（1 元素列表），`do_kv_cache_update` 访问 `kv_cache[1]` 越界。修复为按类型处理：
```python
if isinstance(kv_cache, tuple):
    self.compilation_config.static_forward_context[layer_name].kv_cache = list(kv_cache)
else:
    self.compilation_config.static_forward_context[layer_name].kv_cache = [kv_cache]
```

---

### 3. `vllm_ascend/spec_decode/dflash_proposer.py` — DFlash proposer 配置

**目标**：让 AscendDflashProposer 正确读取 DFlash 配置，并在 profiling 时跳过 draft forward。

**修改点**：

1. **覆写 `_get_eagle3_use_aux_hidden_state_from_config`**：从 `dflash_config`（而非 `eagle_config`）读取 `use_aux_hidden_state`：
```python
@override
def _get_eagle3_use_aux_hidden_state_from_config(self) -> bool:
    use_aux_hidden_state = True
    dflash_config = getattr(
        self.draft_model_config.hf_config, "dflash_config", None
    )
    if dflash_config is not None:
        use_aux_hidden_state = dflash_config.get("use_aux_hidden_state", True)
    return use_aux_hidden_state
```

2. **profiling 时跳过 draft model forward**：profiling 阶段 KV cache 未分配，TP all-reduce 会死锁：
```python
if is_profile:
    self.model.precompute_and_store_context_kv(context_states, context_positions)
    # 跳过 self.model(...) forward
```

---

### 4. `vllm_ascend/spec_decode/llm_base_proposer.py` — Drafter 加载和推理适配

**目标**：解决 drafter 加载时 target 配置泄漏到 draft 的问题。

**修改点**：

1. **`load_model` 中使用 `_MlaSafeConfigProxy`**：drafter 的 `get_kv_cache_spec` 调用传入 target 的 `vllm_config`（`use_mla=True`），draft 的标准 Attention 层有 `sliding_window`，触发断言。用 proxy 替换：
```python
draft_vllm_config = _MlaSafeConfigProxy(self.vllm_config, self.draft_model_config)
# 用 draft_vllm_config 调用 get_kv_cache_spec
```

2. **`_propose` 中检查 draft spec 类型**：`use_compress=True`（来自 target）时，向 draft 的 `builder.build()` 传递 DSA 专用参数。但 draft 用标准 attention，不接受这些参数。添加类型检查：
```python
if self.use_compress:
    draft_spec = self.draft_attn_groups[0].kv_cache_spec
    if isinstance(draft_spec, UniformTypeKVCacheSpecs):
        draft_spec = next(iter(draft_spec.kv_cache_specs.values()))
    if isinstance(draft_spec, (MLAAttentionSpec, SlidingWindowMLASpec)):
        extra_attn_metadata_args = dict(...)  # 只对 MLA/SWA-MLA 传 DSA 参数
```

3. **导入 `SlidingWindowMLASpec`**：
```python
from vllm.v1.kv_cache_interface import MLAAttentionSpec, SlidingWindowMLASpec
```

---

### 5. `vllm_ascend/patch/platform/patch_speculative_config.py` — 防止 DFlash 架构被误转换

**目标**：`hf_config_override` 会将 `model_type="deepseek_v4"` 的 draft 模型转换为 MTP。添加 guard 跳过 DFlash 架构。

```python
def hf_config_override(hf_config):
    initial_architecture = hf_config.architectures[0]
    if initial_architecture.startswith("DFlash"):
        return hf_config  # DFlash draft 不转 MTP
    ...
```

---

### 6. `vllm_ascend/patch/worker/patch_qwen3_dflash.py` — Draft 模型 fc 层尺寸和 KV cache 写入

**目标**：修正 `target_hidden_size` 以匹配 DeepSeek-V4 的 `hc_mult * hidden_size` 维度，并在 KV cache 未绑定时跳过写入。

**修改点**：

1. **`precompute_and_store_context_kv` 添加 null 检查**：如果 `attn.kv_cache` 为 None（未绑定），跳过写入而不是崩溃：
```python
if kv_cache is None:
    logger.warning_once("DFlash draft layer %s has no KV cache bound; skipping...", attn.layer_name)
    continue
```

2. **Patch `DFlashQwen3Model.__init__`**：DeepSeek-V4 的 aux hidden states 是 3D 展平后 `hc_mult * hidden_size` 维，但 draft 配置的 `target_hidden_size` 可能只是 `hidden_size`。在原始 `__init__` 之前修正：
```python
def _patched_dflash_init(self, *, vllm_config, start_layer_id=0, prefix=""):
    target_config = vllm_config.model_config.hf_config
    target_hc_mult = getattr(target_config, "hc_mult", 1)
    if target_hc_mult > 1:
        draft_hf_config = vllm_config.speculative_config.draft_model_config.hf_config
        current_ts = getattr(draft_hf_config, "target_hidden_size", None)
        target_hs = getattr(target_config, "hidden_size", None)
        if current_ts is None:
            draft_hf_config.target_hidden_size = target_hs * target_hc_mult
        elif target_hs is not None and current_ts == target_hs:
            draft_hf_config.target_hidden_size = current_ts * target_hc_mult
    _original_dflash_init(self, vllm_config=vllm_config, ...)  # 用修正后的 config 创建 fc
```

**为什么 `_original_dflash_init` 在最后调用**：必须先修改 `target_hidden_size`，再调用原始 `__init__`，因为 `__init__` 会读取 `target_hidden_size` 来创建 `fc` 层（`fc_input_size = target_hidden_size * num_features`）。如果先调用 `__init__`，`fc` 已经用错误尺寸创建了。

---

### 7. `vllm_ascend/patch/platform/patch_kv_cache_utils.py` — KV cache 分组适配

**目标**：DeepSeek-V4 的自定义 KV cache 分组逻辑只处理 `MLAAttentionSpec` 和 `SlidingWindowMLASpec`，不处理 draft 层的 `SlidingWindowSpec`/`FullAttentionSpec`。

**修改点**：

1. **`group_and_unify_kv_cache_specs`**：添加 `else` 分支收集非 MLA/非 SWA-MLA 的 spec（draft 层），作为单独的 `UniformTypeKVCacheSpecs` 返回：
```python
other_specs = {}
for name, spec in kv_cache_spec.items():
    if isinstance(spec, SlidingWindowMLASpec): ...
    elif isinstance(spec, MLAAttentionSpec): ...
    else:
        other_specs[name] = spec  # draft 层
...
return [*mla_uniform_specs, *swa_uniform_specs, *other_uniform_specs]
```

2. **`_get_kv_cache_groups_uniform_groups`**：将 `grouped_specs[2:]` 按类型分离——SWA-MLA 走原有对齐逻辑，其他（draft 层）直接创建 `KVCacheGroupSpec`：
```python
swa_mla_specs = []
other_specs = []
for g in grouped_specs[2:]:
    if all(isinstance(spec, SlidingWindowMLASpec) for spec in g.kv_cache_specs.values()):
        swa_mla_specs.append(g)
    else:
        other_specs.append(g)
# SWA 走原有逻辑，other 直接创建简单 group
```

3. **`_get_kv_cache_config_deepseek_v4`**：在层遍历中，将非 MLA/非 SWA-MLA 层（draft 层）单独收集，最后为每个 draft 层创建独立的 `KVCacheTensor`（类似 MTP 层的处理方式）：
```python
for name in group.layer_names:
    if "mtp" in name: ...
    elif isinstance(specs[name], (SlidingWindowMLASpec, MLAAttentionSpec)):
        b[specs[name].page_size_bytes].append(name)
    else:
        other_layer_names.append(name)  # draft 层
        other_page_sizes[name] = specs[name].page_size_bytes
...
for name in other_layer_names:
    kv_cache_tensors.append(KVCacheTensor(size=other_page_sizes[name] * num_blocks, shared_by=[name]))
```

---

## 数据流总结

```
Target (DeepSeek-V4) forward
  ├─ 每层收集 aux hidden states (3D: num_tokens × hc_mult × hidden_size)
  │  └─ hc_post 已合并 residual，不再加 residual
  ├─ 返回 (hidden_states, aux_hidden_states)
  │
Model Runner
  ├─ aux_hidden_states → flatten(1) → 2D (num_tokens × hc_mult*hidden_size)
  ├─ 拼接: torch.cat([...], dim=-1) → (num_tokens × 81920)
  └─ 传给 drafter._propose(target_hidden_states=...)
        │
Drafter._propose
  ├─ combine_hidden_states: fc(81920 → 4096) 投影到 draft 空间
  ├─ set_inputs_first_pass: 存入 _dflash_hidden_states
  └─ _run_merged_draft
       ├─ build_model_inputs_first_pass
       │    └─ precompute_and_store_context_kv: RMSNorm + KV投影 → 写入 KV cache
       └─ draft model forward: 交叉注意力读取 KV cache → 生成 draft tokens
```