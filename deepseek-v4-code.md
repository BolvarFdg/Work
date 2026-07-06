现在我已掌握所有所需信息，可以呈现完整的流程了。

---

## DeepSeek-V4 DFlash 投机推理：大模型 + 小模型 全流程

### 一、整体时序图

```
┌─────────────── 大模型 (Target) ───────────────┐
│                                                │
│  SchedulerOutput → execute_model()             │
│  ├─ input_ids, positions                       │
│  ├─ Embedding → hc_mult扩展 → Decoder层循环    │
│  │   ├─ hc_pre → RMSNorm → Attention(DSA)     │
│  │   ├─ hc_post → hc_pre → RMSNorm → MoE     │
│  │   ├─ hc_post → (逐层收集 aux_hidden_states) │
│  │   └─ ... × num_layers                       │
│  ├─ 保存 pre-hc_head残差 → _mtp_hidden_buffer │
│  ├─ hc_head → RMSNorm → hidden_states         │
│  ├─ hidden_states[logits_indices]              │
│  ├─ LM Head → LogitsProcessor → logits        │
│  └─ 返回 (hidden_states, aux_hidden_states)    │
│                                                │
│  sample_tokens():                              │
│  ├─ AscendSampler(logits) → sampled_token_ids  │
│  └─ propose_draft_token_ids():                 │
│    ├─ get_mtp_target_hidden_states()           │
│    │   → hidden_states = _mtp_hidden_buffer   │
│    ├─ aux拼接 → target_hidden_states           │
│    └─ drafter._propose(...)                    │
│                                                │
└────────────────────────────────────────────────┘
                     ↓
┌─────────────── 小模型 (Draft) ────────────────┐
│                                                │
│  AscendDflashProposer._propose():              │
│  ├─ ① combine_hidden_states()                  │
│  │   fc(aux拼接向量) → draft维度hidden_size    │
│  ├─ ② set_inputs_first_pass()                 │
│  │   ├─ 存target_hidden_states到buffer         │
│  │   ├─ Triton kernel构造: input_ids,          │
│  │   │  positions, slot_mapping,               │
│  │   │  token_indices_to_sample                │
│  │   ├─ 设置 causal=False, ChunkedPrefill     │
│  │   └─ 返回 num_query_total, cad              │
│  ├─ ③ build_model_inputs_first_pass()         │
│  │   ├─ precompute_and_store_context_kv()      │
│  │   │   target_hidden_states → KV投影 →       │
│  │   │   RMSNorm → RoPE → 写入KV cache        │
│  │   └─ 返回 {input_ids, positions}            │
│  ├─ ④ 构建注意力metadata (非因果)              │
│  ├─ ⑤ Draft Model Forward:                    │
│  │   DeepSeekV4MTP.forward()                   │
│  │   ├─ embed_tokens(mask_token_ids)           │
│  │   ├─ enorm(embed) + hnorm(prev_hidden)      │
│  │   ├─ e_proj(embed) + h_proj(prev_hidden)    │
│  │   │   → 特征融合                            │
│  │   ├─ DeepseekV2DecoderLayer                 │
│  │   │   (非因果DSA Attention + MoE)            │
│  │   └─ 返回 pre-hc_head残差                   │
│  ├─ ⑥ compute_logits / compute_draft_token_ids │
│  │   ├─ hc_head → shared_head.norm             │
│  │   ├─ LM Head → logits                      │
│  │   └─ greedy_sample → draft_token_ids        │
│  └─ 返回 draft_token_ids                       │
│                                                │
└────────────────────────────────────────────────┘
                     ↓
┌─────────────── 拒绝采样 ───────────────────────┐
│                                                │
│  AscendRejectionSampler:                       │
│  ├─ target_logits.softmax() → target_probs    │
│  ├─ 对比 draft_probs vs target_probs          │
│  ├─ 接受匹配的draft tokens                    │
│  ├─ 拒绝不匹配的 → 从target_probs重新采样     │
│  └─ 返回最终accepted tokens                   │
│                                                │
│  Scheduler.update_from_output():               │
│  ├─ 更新 num_computed_tokens                  │
│  └─ update_draft_token_ids(new_drafts)         │
│     → 存入 request.spec_token_ids             │
│     → 下次schedule包含spec tokens             │
└────────────────────────────────────────────────┘
```

---

### 二、大模型 (Target) 详细流程

**入口**: `NPUModelRunner.execute_model()` (`model_runner_v1.py:1927`)

| 步骤 | 代码位置 | 输入 → 输出 | 说明 |
|------|---------|------------|------|
| **1. 准备输入** | `model_runner_v1.py:1990-2062` `_prepare_inputs` | SchedulerOutput → input_ids[T], positions[T], logits_indices | 构造模型输入tensor |
| **2. Embedding** | `deepseek_v4.py:1116` | input_ids[T] → hidden_states[T, D] | `VocabParallelEmbedding` 词嵌入 |
| **3. hc_mult扩展** | `deepseek_v4.py:1136` | (T,D) → (T, hc_mult, D) | `unsqueeze(1).repeat(1, hc_mult, 1)`，每个token扩展为4个流 |
| **4. Decoder层循环** | `deepseek_v4.py:1140-1144` | (T, hc_mult, D) → (T, hc_mult, D) + aux_hidden_states | 每层：hc_pre→RMSNorm→DSA→hc_post→hc_pre→RMSNorm→MoE→hc_post |
| **5. 逐层收集aux** | `deepseek_v4.py:1138-1143` `_maybe_add_hidden_states` | 指定层的 hidden_states+residual | 在层idx∈aux_hidden_state_layers(如2,61,123)时append |
| **6. 保存MTP残差** | `deepseek_v4.py:1164-1165` | hidden_states.flatten(1) → `_mtp_hidden_buffer` | 保存pre-hc_head残差供小模型使用 |
| **7. hc_head** | `deepseek_v4.py:1096-1103` | (T, hc_mult, D) → (T, D) | RMSNorm→Linear→Sigmoid门控→加权求和，压缩多流回单流 |
| **8. 最终RMSNorm** | `deepseek_v4.py:1176` | (T,D) → (T,D) | 最终归一化 |
| **9. 返回** | `deepseek_v4.py:1178-1179` | → (hidden_states, aux_hidden_states) | 元组返回 |
| **10. compute_logits** | `deepseek_v4.py:1287-1292` `AscendDeepseekV4ForCausalLM` | hidden_states[T,D] → logits[T, vocab_size] | `LogitsProcessor(lm_head, hidden_states)` → ParallelLMHead投影→TP gather |
| **11. Sampling** | `model_runner_v1.py:2413` `AscendSampler` | logits → sampled_token_ids | top_k/top_p → softmax → random_sample / greedy |
| **12. MTP残差替换** | `model_runner_v1.py:1813-1817` | hidden_states → `_mtp_hidden_buffer` | `get_mtp_target_hidden_states()` 返回pre-hc_head残差 |
| **13. aux拼接** | `model_runner_v1.py:1827-1835` | aux_hidden_states → (T, hc_mult*D*num_aux_layers) | `torch.cat([h.flatten(1) for h in aux_hidden_states], dim=-1)` |
| **14. 调用drafter** | `model_runner_v1.py:1874-1890` | target数据 → draft_token_ids | `drafter._propose()` |

---

### 三、小模型 (Draft/MTP) 详细流程

**入口**: `AscendDflashProposer._propose()` (`llm_base_proposer.py:627`)

| 步骤 | 代码位置 | 输入 → 输出 | 说明 |
|------|---------|------------|------|
| **① combine_hidden_states** | `patch_qwen3_dflash.py:140-152` (对Qwen3) 或 `llm_base_proposer.py:671` | (T, hc_mult*D*num_aux_layers) → (T, draft_hidden_size) | fc线性层将高维aux拼接特征投影到draft模型维度。DeepSeek-V4的draft模型(DFlashQwen3)用此映射 |
| **② set_inputs_first_pass** | `dflash_proposer.py:63-148` | target数据 → (num_query_total, token_indices_to_sample, modified_cad) | 核心：构造draft模型输入。Triton kernel `copy_and_expand_dflash_inputs_kernel_single_grid` 生成mask_token_ids(并行draft位置)、positions、slot_mapping；设`causal=False`+`ChunkedPrefill` |
| **③ precompute_and_store_context_kv** | `dflash_proposer.py:250-264` → `patch_qwen3_dflash.py:45-138` | target_hidden_states → 写入KV cache | **关键**：将target模型的hidden_states直接投影为K/V，经RMSNorm+RoPE后写入KV cache，context tokens不经过draft模型前向 |
| **④ 构建注意力metadata** | `llm_base_proposer.py:832` | cad → attn_metadata | 非因果(causal=False) cross-attention metadata |
| **⑤ Draft Model Forward** | `llm_base_proposer.py:1052` `self.model(**model_kwargs)` | input_ids, positions → hidden_states | DFlashQwen3ForCausalLM.forward() → DFlashQwen3Model.forward() |
| **⑥ 内部: embed** | DFlashQwen3Model | mask_token_ids → embeddings | 并行draft: 每个请求1个bonus token + num_spec个mask token |
| **⑦ 内部: DFlash cross-attn** | DFlashQwen3Model | Q来自embeddings, K/V来自预填的context KV | 非因果注意力：draft tokens看到context tokens |
| **⑧ 内部: Transformer层** | DFlashQwen3Model | hidden_states → hidden_states | 标准transformer层(非因果注意力+FFN) |
| **⑨ compute_draft_token_ids** | `llm_base_proposer.py:984-999` | sample_hidden_states → draft_token_ids | `model.logits_processor(model.lm_head, hidden_states)` → `greedy_sample(logits)` → 可选 d2t vocab mapping |

---

### 四、关键数据维度变化

```
大模型:
  input_ids:          [T]                    (T = num_scheduled_tokens)
  embedding:          [T, D]                 (D = hidden_size, 如7168)
  hc_mult扩展:        [T, 4, D]              (hc_mult=4)
  decoder循环:        [T, 4, D]              (每层保持4流)
  aux_hidden_states:  [3个tensor, 各(T,4,D)] (如层2/61/123处收集)
  _mtp_hidden_buffer: [T, 4*D]               (pre-hc_head残差)
  hc_head输出:        [T, D]                 (压缩回单流)
  logits:             [T, vocab_size]         (如129280)

小模型准备:
  aux拼接:            [T, 4*D*3]             = [T, hc_mult*hidden_size*num_aux_layers]
  combine_hidden:     [T, D_draft]           (fc投影到draft维度)
  context KV预填:     [L, num_ctx, nkv, hd]  (所有层的K/V一次性计算)

小模型:
  draft input_ids:    [batch*(1+num_spec)]   (1个bonus+num_spec个mask)
  draft positions:    [batch*(1+num_spec)]
  draft hidden_states: [batch*(1+num_spec), D_draft]
  draft logits:       [batch*num_spec, vocab_size]
  draft_token_ids:    [batch, num_spec]
```

---

### 五、DFlash 的核心设计

DFlash 与传统 MTP 串行投机的关键区别是 **并行drafting**：

- **传统MTP**: 串行，先算target token1→draft token2→draft token3→...，每次需等前一步完成
- **DFlash**: 并行，所有draft tokens **同时** 前向。通过 **非因果cross-attention**，让每个draft token都能看到context (target hidden_states)，不依赖序列因果顺序

实现机制：
1. `precompute_and_store_context_kv()` 将target hidden_states直接写入KV cache作为context
2. Draft tokens通过cross-attention读取context KV，自身之间不做因果mask (`causal=False`)
3. 所有draft tokens在一次forward中同时产出，极大减少延迟