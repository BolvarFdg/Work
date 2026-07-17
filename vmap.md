修改正确。让我验证 `mask_mod` 函数在 broadcasting 下的行为是否符合预期——所有操作都支持 broadcasting，无需 `torch.vmap`：

```
b = [B, 1, 1, 1],  h = [1, H, 1, 1],  q = [1, 1, Q_LEN, 1],  kv = [1, 1, 1, KV_LEN]

base_prefix_mod:
  query_anchor_positions[q_idx]     → [1, 1, Q_LEN, 1]    (advanced indexing)
  document_ids[q_anchor]            → [1, 1, Q_LEN, 1]    (advanced indexing)
  kv_idx < total_seq_len            → [1, 1, 1, KV_LEN]
  q_doc == kv_doc                   → [1, 1, Q_LEN, KV_LEN] (broadcast)
  
same_block_mod:
  q_idx // block_size               → [1, 1, Q_LEN, 1]
  kv_idx >= total_seq_len           → [1, 1, 1, KV_LEN]
  q_block == kv_block               → [1, 1, Q_LEN, KV_LEN] (broadcast)

or_masks → [1, 1, Q_LEN, KV_LEN]  ✅
```

修改已应用。总结一下这次排查的完整链路：

### 根因

`flex_attention.create_mask`（`attention.py:83` 原来调用的 `_create_mask`）内部对 `mask_mod` 做了 **4 层 `torch.vmap` 嵌套**（`flex_attention.py:351-393`）来在 batch/head/Q/KV 维度上广播。**`torch.vmap` 在 Ascend NPU 上不支持，会卡死 stream**，导致后续操作超时。

### 修复

`src/speculators/models/attention.py:69-101`：将 `create_float_mask` 从调用 `flex_attention.create_mask`（内部用 `torch.vmap`）改为**纯 tensor broadcasting** 直接评估 `mask_mod`——用 `view` + 广播代替 `vmap`，功能等价但完全绕开了 `torch.vmap`。

现在可以用单卡 + `--draft-attn-impl eager --max-anchors 32` 重新跑训练试试。如果还有问题，可能需要在 `select_anchors`（`dflash/utils.py`）或 `eager_attention_forward`（transformers 内置）处进一步排查。