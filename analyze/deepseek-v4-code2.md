# DeepSeek-V4 DFlash 投机推理完整流程

## 总体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     用户请求 (Request)                        │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  vllm: Scheduler → SchedulerOutput                           │
│  (调度器决定哪些 request 参与本次 forward)                      │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  vllm-ascend: NPUModelRunner.execute_model()                 │
│  (model_runner_v1.py)                                         │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  阶段1: Target 模型 Forward (DeepSeek-V4)            │     │
│  │  → 产出 hidden_states + aux_hidden_states            │     │
│  └───────────────────────┬─────────────────────────────┘     │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  阶段2: 采样 (Sampling)                              │     │
│  │  → 产出 target 的 next_token_ids                     │     │
│  └───────────────────────┬─────────────────────────────┘     │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  阶段3: DFlash Draft 投机提议                          │     │
│  │  (AscendDflashProposer)                              │     │
│  │  → 产出 draft_token_ids (投机 token)                  │     │
│  └───────────────────────┬─────────────────────────────┘     │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  阶段4: 验证 (Verification)                           │     │
│  │  Target 模型再次 forward 验证 draft tokens            │     │
│  └───────────────────────┬─────────────────────────────┘     │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────┐     │
│  │  阶段5: 拒绝采样 (Rejection Sampling)                 │     │
│  │  → 决定接受/拒绝哪些 draft tokens                      │     │
│  └───────────────────────┬─────────────────────────────┘     │
└──────────────────────────┼──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    ModelRunnerOutput                          │
│              (接受的目标 tokens → 返回用户)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 阶段 1: Target 模型 Forward

### 入口

```
vllm-ascend/worker/model_runner_v1.py
  NPUModelRunner.execute_model()
    → NPUModelRunner._model_forward()
```

### 调用链

```
NPUModelRunner._model_forward()
│
├── vllm-ascend/models/deepseek_v4.py
│   AscendDeepseekV4ForCausalLM.forward()
│   │
│   └── DeepseekV4Model.forward()
│       │
│       ├── embed_input_ids(input_ids)           # Token → Embedding
│       │   └── VocabParallelEmbedding.forward()
│       │
│       ├── hidden_states.unsqueeze(1).repeat(1, hc_mult, 1)
│       │   # 2D→3D: [num_tokens, hidden] → [num_tokens, hc_mult, hidden]
│       │
│       ├── aux_hidden_states = _maybe_add_hidden_state([], 0, hidden_states, residual)
│       │   # 初始调用（收集 embedding，如果 idx=0 在 aux_layers 中）
│       │
│       ├── for idx, layer in enumerate(layers):  ←── 外层循环（逐层）
│       │   │
│       │   ├── hidden_states, residual = layer.forward(positions, hidden_states, residual)
│       │   │   │
│       │   │   │  vllm-ascend/models/deepseek_v4.py
│       │   │   │  DeepseekV2DecoderLayer.forward()
│       │   │   │
│       │   │   ├── residual = hidden_states.clone()           # 保存输入
│       │   │   ├── hidden_states, post, comb = hc_pre(...)    # 超压缩预处理
│       │   │   │   └── torch.ops._C_ascend.npu_hc_pre()
│       │   │   ├── hidden_states = input_layernorm(hidden_states)
│       │   │   │   └── RMSNorm.forward()
│       │   │   ├── hidden_states = self_attn(positions, hidden_states)
│       │   │   │   │  DeepseekV4Attention.forward()
│       │   │   │   │  ├── qkv_proj (QKVParallelLinear)
│       │   │   │   │  ├── rotary_emb (RoPE)
│       │   │   │   │  ├── attn (Attention) → AscendAttentionBackendImpl
│       │   │   │   │  └── o_proj (RowParallelLinear)
│       │   │   ├── hidden_states = hc_post(hidden_states, residual, post, comb)
│       │   │   │   └── torch.ops._C_ascend.npu_hc_post()      # 合并残差
│       │   │   ├── residual = hidden_states.clone()           # post-attn 值
│       │   │   ├── hidden_states, post, comb = hc_pre(...)
│       │   │   ├── hidden_states = post_attention_layernorm(hidden_states)
│       │   │   ├── hidden_states = mlp(hidden_states)
│       │   │   │   └── DeepseekV4MoE (MoE MLP)
│       │   │   └── hidden_states = hc_post(hidden_states, residual, post, comb)
│       │   │
│       │   └── _maybe_add_hidden_state(aux, idx+1, hidden_states, residual)
│       │       # 收集 aux hidden state（如果 idx+1 在 aux_layers 中）
│       │       # DeepSeek-V4: 用 hidden_states 单独（不加 residual）
│       │
│       ├── _mtp_hidden_buffer.copy_(hidden_states.flatten(1))  # 缓存 pre-hc_head
│       │
│       ├── hidden_states = hc_head(hidden_states, ...)          # 3D→2D 压缩
│       │   └── RMSNorm + Linear + Sigmoid + WeightedSum
│       │
│       ├── hidden_states = norm(hidden_states)                  # 最终 RMSNorm
│       │
│       └── return (hidden_states, aux_hidden_states)
│           # 返回: 最终 hidden_states + aux_hidden_states 列表
│
├── vllm-ascend: AscendSampler → logits = model.compute_logits(sample_hidden_states)
│
└── 存入 ExecuteModelState(hidden_states, aux_hidden_states, ...)
```

### 数据流图

```
input_ids: [num_tokens]
    │
    ▼
embed_tokens → [num_tokens, hidden]
    │
    ▼  repeat(hc_mult)
[num_tokens, hc_mult, hidden]  ← 3D
    │
    ├──→ Layer 0 ──→ Layer 1 ──→ ... ──→ Layer 42
    │     │            │                    │
    │     │  aux[0]    │  aux[1]      aux[4]
    │     ▼            ▼                    ▼
    │   [T,4,H]      [T,4,H]            [T,4,H]  ← aux_hidden_states (5个)
    │
    ▼
hc_head (3D→2D) → [num_tokens, hidden]
    │
    ▼
norm → lm_head → logits → sample → target next_token_ids
```

---

## 阶段 2: 采样

```
vllm-ascend/worker/model_runner_v1.py
  NPUModelRunner.sample_tokens()
    │
    ├── 解包 ExecuteModelState (hidden_states, aux_hidden_states, ...)
    │
    ├── self._sample(logits, spec_decode_metadata)
    │   └── vllm-ascend: AscendSampler
    │       → sampled_token_ids (目标的预测 token)
    │
    └── 调用 propose_draft_token_ids(sampled_token_ids)  → 进入阶段3
```

---

## 阶段 3: DFlash Draft 投机提议（核心）

### 入口

```
vllm-ascend/worker/model_runner_v1.py
  NPUModelRunner.propose_draft_token_ids()
    │
    ├── 构建 target_hidden_states:
    │   # 从 aux_hidden_states 拼接 + flatten
    │   target_hidden_states = torch.cat(
    │       [h[:n].flatten(1) if h.dim() > 2 else h[:n]
    │        for h in aux_hidden_states], dim=-1)
    │   # shape: [num_tokens, num_aux * hc_mult * hidden]
    │
    └── self.drafter._propose(target_token_ids=..., target_hidden_states=..., ...)
```

### _propose 内部调用链

```
vllm-ascend/spec_decode/llm_base_proposer.py
  AscendSpecDecodeBaseProposer._propose()
  │
  ├─── 3a. FC 投影
  │    target_hidden_states = self.model.combine_hidden_states(target_hidden_states)
  │    │
  │    │  vllm/model_executor/models/qwen3_dflash.py
  │    │  DFlashQwen3ForCausalLM.combine_hidden_states()
  │    │    └── self.model.fc(hidden_states)
  │    │        └── ReplicatedLinear.forward()
  │    │
  │    │  [num_tokens, num_aux * hc_mult * hidden]
  │    │      →FC→ [num_tokens, draft_hidden]  (4096)
  │    └────────────────────────────────────────────────
  │
  ├─── 3b. 输入准备 + Precompute KV（eager 模式，图前执行）
  │    num_tokens, token_indices, cad, _ = self.set_inputs_first_pass(...)
  │    │
  │    │  vllm-ascend/spec_decode/dflash_proposer.py
  │    │  AscendDflashProposer.set_inputs_first_pass()
  │    │    │
  │    │    ├── 存储 combined hidden states:
  │    │    │   self._dflash_hidden_states[:num_context] = target_hidden_states
  │    │    │
  │    │    ├── Triton Kernel:
  │    │    │   vllm-ascend/ops/triton/spec_decode/utils.py
  │    │    │   copy_and_expand_dflash_inputs_kernel_single_grid()
  │    │    │     → 生成: input_ids(bonus+mask), positions,
  │    │    │              context_slot_mapping, query_slot_mapping,
  │    │    │              token_indices_to_sample
  │    │    │
  │    │    ├── 设置 non-causal:
  │    │    │   cad.causal = False
  │    │    │   cad.attn_mask = None
  │    │    │   cad.attn_state = ChunkedPrefill
  │    │    │
  │    │    └── Precompute KV (eager, 不进图):
  │    │        self.model.precompute_and_store_context_kv(
  │    │            self._dflash_hidden_states[:num_context],
  │    │            self._context_positions_buffer[:num_context],
  │    │            self._context_slot_mapping_buffer[:num_context])
  │    │        │
  │    │        │  vllm-ascend/patch/worker/patch_qwen3_dflash.py
  │    │        │  DFlashQwen3Model.precompute_and_store_context_kv()
  │    │        │    │
  │    │        │    ├── (a) RMSNorm context states
  │    │        │    │    self.hidden_norm(context_states)
  │    │        │    │
  │    │        │    ├── (b) Fused KV projection (一次 GEMM 所有层)
  │    │        │    │    F.linear(normed, self._fused_kv_weight, self._fused_kv_bias)
  │    │        │    │    → [num_ctx, L * 2 * kv_size]
  │    │        │    │
  │    │        │    ├── (c) Per-layer K RMSNorm
  │    │        │    │    for i: k_norm_layer(all_k[i])
  │    │        │    │
  │    │        │    ├── (d) Fused RoPE (所有层)
  │    │        │    │    rotary_emb(positions_repeated, all_k_flat, tmpv)
  │    │        │    │    → 对 K 应用旋转位置编码
  │    │        │    │
  │    │        │    └── (e) Per-layer 写入 KV cache
  │    │        │         for i: attn.impl.do_kv_cache_update(
  │    │        │             attn, all_k_final[i], all_v[i], kv_cache, slot_mapping)
  │    │        │         └── DeviceOperator.reshape_and_cache()
  │    │        │
  │    │        └── 返回 (num_query_total, token_indices, cad, None)
  │    └────────────────────────────────────────────────────────
  │
  ├─── 3c. 构建 Attention Metadata
  │    │
  │    │  vllm-ascend/attention/attention_v1.py
  │    │  AscendAttentionMetadataBuilder.build()
  │    │    → 生成 AscendMetadata (attn_state, slot_mapping, block_table, ...)
  │    │
  │    │  if causal=False:
  │    │    attn_metadata.attn_mask = None    # 非因果，不需要 mask
  │    └────────────────────────────────────
  │
  ├─── 3d. Draft 模型 Forward（图模式: ACLGraphWrapper replay）
  │    │
  │    │  self._runnable(**model_inputs)
  │    │  │
  │    │  │  eager: _run_merged_draft()
  │    │  │  graph: ACLGraphWrapper(_run_merged_draft)
  │    │  │
  │    │  │  vllm-ascend/spec_decode/llm_base_proposer.py
  │    │  │  AscendSpecDecodeBaseProposer._run_merged_draft()
  │    │  │    │
  │    │  │    ├── build_model_inputs_first_pass(num_input_tokens)
  │    │  │    │   → 只返回 kwargs (input_ids, positions, inputs_embeds=None)
  │    │  │    │     precompute 已在 3b 完成
  │    │  │    │
  │    │  │    └── self.model(**model_kwargs)
  │    │  │        │
  │    │  │        │  vllm/model_executor/models/qwen3_dflash.py
  │    │  │        │  DFlashQwen3ForCausalLM.forward()
  │    │  │        │    └── DFlashQwen3Model.forward()
  │    │  │        │        │
  │    │  │        │        ├── embed_input_ids(input_ids)
  │    │  │        │        │   # bonus token + mask tokens → embeddings
  │    │  │        │        │
  │    │  │        │        ├── for layer in self.layers:  ←── draft 逐层
  │    │  │        │        │   │
  │    │  │        │        │   └── DFlashQwen3DecoderLayer.forward()
  │    │  │        │        │       │
  │    │  │        │        │       ├── input_layernorm(hidden_states, residual)
  │    │  │        │        │       │   └── RMSNorm: residual = h+r; h = norm(residual)
  │    │  │        │        │       │
  │    │  │        │        │       ├── self_attn(positions, hidden_states)
  │    │  │        │        │       │   │  DFlashQwen3Attention.forward()
  │    │  │        │        │       │   │
  │    │  │        │        │       │   ├── qkv_proj: F.linear(h, qkv_weight)
  │    │  │        │        │       │   │   → q, k, v
  │    │  │        │        │       │   ├── q_norm, k_norm (RMSNorm per-head)
  │    │  │        │        │       │   ├── rotary_emb(positions, q, k)
  │    │  │        │        │       │   │   └── RoPE 应用于 query K
  │    │  │        │        │       │   ├── attn(q, k, v)
  │    │  │        │        │       │   │   │  vllm: Attention.forward()
  │    │  │        │        │       │   │   │  → reshape_and_cache (写 query K/V)
  │    │  │        │        │       │   │   │  → attention 计算
  │    │  │        │        │       │   │   │
  │    │  │        │        │       │   │   │  vllm-ascend: attention_v1.py
  │    │  │        │        │       │   │   │  AscendAttentionBackendImpl
  │    │  │        │        │       │   │   │    .forward_fused_infer_attention()
  │    │  │        │        │       │   │   │
  │    │  │        │        │       │   │   │  ┌─ 图捕获: full_graph_fia()
  │    │  │        │        │       │   │   │  │  sparse_mode=0 (non-causal)
  │    │  │        │        │       │   │   │  │  attn_mask=None
  │    │  │        │        │       │   │   │  │  npu_fused_infer_attention_score()
  │    │  │        │        │       │   │   │  └─ 图replay: 重放捕获的op
  │    │  │        │        │       │   │   │
  │    │  │        │        │       │   │   │  非图模式: 直接调用
  │    │  │        │        │       │   │   │  if not causal:
  │    │  │        │        │       │   │   │    sparse_mode=0, npu_fused_infer_attention_score()
  │    │  │        │        │       │   │   │
  │    │  │        │        │       │   ├── o_proj: F.linear(attn_out, o_weight)
  │    │  │        │        │       │
  │    │  │        │        │       ├── post_attention_layernorm(h, residual)
  │    │  │        │        │       └── mlp(hidden_states)
  │    │  │        │        │           ├── gate_up_proj → SiLU → down_proj
  │    │  │        │        │           └── Qwen3MLP
  │    │  │        │        │
  │    │  │        │        ├── norm(hidden_states, residual)  # 最终 RMSNorm
  │    │  │        │        └── return hidden_states
  │    │  │        │            # [num_query_tokens, draft_hidden]
  │    │  │        │
  │    │  │        ├── sample_hidden_states = hidden[token_indices_to_sample]
  │    │  │        │   # 提取投机位置的 hidden states
  │    │  │        │
  │    │  │        └── compute_draft_token_ids(sample_hidden_states)  → 进入 3e
  │    └────────────────────────────────────────────────────────────
  │
  ├─── 3e. Draft Token 计算
  │    │
  │    │  vllm-ascend/spec_decode/llm_base_proposer.py
  │    │  AscendSpecDecodeBaseProposer.compute_draft_token_ids()
  │    │    │
  │    │    ├── logits = logits_processor(lm_head, sample_hidden_states)
  │    │    │   # [num_samples, draft_vocab]  (如 32000)
  │    │    │
  │    │    ├── if d2t exists:
  │    │    │   next_token = greedy_sample(logits)   # argmax + TP all_gather
  │    │    │   bias = draft_id_to_target_id[next_token]  # d2t 映射
  │    │    │   return next_token + bias             # [num_samples] → target vocab
  │    │    │
  │    │    └── else (no d2t):
  │    │        return greedy_sample(logits)
  │    │
  │    │  或 (非 enable_reduce_sample 路径):
  │    │  logits = model.compute_logits(sample_hidden_states)
  │    │    # 构建 full target_vocab logits (-inf for non-draft tokens)
  │    │  draft_token_ids = logits.argmax(dim=-1)
  │    └────────────────────────────────────────────
  │
  └── return draft_token_ids  # [batch_size, num_speculative_tokens]
```

### DFlash Draft 数据流图

```
                    Target 模型产出
                    ┌──────────────────────────────────────┐
                    │ aux_hidden_states: 5个 [T,4,4096]    │
                    └───────────────┬──────────────────────┘
                                    │ flatten + cat
                                    ▼
                    [T, 81920]  (5 × 4 × 4096)
                                    │
                        FC 投影 (combine_hidden_states)
                                    │
                                    ▼
                    [T, 4096]  (combined hidden states)
                                    │
                     ┌──────────────┴──────────────┐
                     ▼                               ▼
              Precompute KV                    存入 buffer
              (eager, 图前)                  _dflash_hidden_states
                     │
              ┌──────┼──────┐
              ▼      ▼      ▼
           RMSNorm  GEMM   RoPE
              │      │      │
              └──────┼──────┘
                     ▼
              写入 Draft KV Cache
              (context K/V, 所有层)
                     │
                     │  ──────────────── 图模式分割线 ────────────────
                     │           (以上 eager, 以下 graph replay)
                     ▼
              Draft 模型 Forward
              ┌──────────────────────────────────┐
              │ input_ids: [bonus, mask×6]        │
              │ positions: [last+1, last+2, ...]  │
              └──────────────┬───────────────────┘
                             ▼
              DFlashQwen3Model.forward()
              ├── embed → [7, 4096]
              ├── Layer 0: attn(Q→KV cache) + mlp
              ├── Layer 1: attn(Q→KV cache) + mlp
              ├── ...
              ├── Layer 4: attn(Q→KV cache) + mlp
              └── norm → [7, 4096]
                             │
                             ▼  token_indices_to_sample
              sample_hidden_states [6, 4096]
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
              lm_head           greedy_sample
              [6, draft_vocab]       │
                    │                 │
                    └────────┬────────┘
                             ▼
                    d2t 映射 (next_token + bias)
                             │
                             ▼
              draft_token_ids [batch, num_spec]  → 提交给验证阶段
```

---

## 阶段 4: 验证 (Verification)

```
vllm-ascend/worker/model_runner_v1.py
  NPUModelRunner (下一轮 execute_model)
    │
    ├── 将 draft_token_ids 加入输入序列
    │   (target 模型对 [original_tokens + draft_tokens] 做 forward)
    │
    └── Target 模型再次 forward (同阶段1)
        → 产出 spec_decode_metadata (验证结果)
```

---

## 阶段 5: 拒绝采样 (Rejection Sampling)

```
vllm-ascend/worker/model_runner_v1.py
  NPUModelRunner.sample_tokens()
    │
    ├── if spec_decode_metadata is not None:
    │   │
    │   └── vllm-ascend: AscendRejectionSampler
    │       │
    │       ├── 比较 draft_token_ids 和 target 的 sampled_token_ids
    │       │   对每个位置: 如果 draft[i] == target[i] → 接受
    │       │             如果 draft[i] != target[i] → 拒绝，用 target[i] 替换
    │       │
    │       └── 产出 valid_sampled_token_ids
    │           # [num_reqs, num_spec+1]  (-1 表示拒绝)
    │
    └── 返回给下一轮 propose（带 rejection 信息）
```

### 拒绝采样图示

```
Draft tokens:   [A, B, C, D, E, F, G]   (7个投机 token)
Target tokens:  [A, B, X, ..., ...]     (验证 forward 产出)
                  ✓  ✗
                  │  └── C≠X → 拒绝 C 及之后所有
                  │
                  ▼
接受结果:        [A, B, X]               (接受2个 + bonus 1个 = 3个实际 token)
                └ bonus ─┘
```

---

## 阶段 6: 输出

```
vllm: ModelRunnerOutput
  ├── accepted_token_ids: 接受的 token
  ├── num_accepted_tokens: 接受数量
  └── 返回给 Scheduler → Engine → 用户
```

---

## 图模式 vs Eager 模式

```
                    ┌─── Eager 模式 ───┐    ┌─── 图模式 ──────┐
                    │                  │    │                  │
Precompute KV       │  eager 执行       │    │  eager 执行        │  ← 已修复
                    │  (set_inputs_    │    │  (set_inputs_     │
                    │   first_pass内)   │    │   first_pass内)    │
                    │                  │    │                  │
Draft Forward       │  eager 执行       │    │  ACLGraph replay  │
                    │  (_run_merged_   │    │  (ACLGraphWrapper  │
                    │   draft直接调用)  │    │   replay)         │
                    │                  │    │                  │
attn forward        │  forward_fused_  │    │  full_graph_fia   │
                    │  infer_attention  │    │  (sparse_mode=0)  │  ← 已修复
                    │  (sparse_mode=0)  │    │                  │
                    └──────────────────┘    └──────────────────┘
```

### 关键修复点

| 修复 | 文件 | 原因 |
|------|------|------|
| precompute 移到 eager | `dflash_proposer.py` | `rotary_emb` 的 host-device copy 不兼容 ACL graph |
| `sparse_mode` 优先级 | `attention_v1.py` | `full_graph_fia` 里 `sliding_window` 优先于 `causal`，导致 DFlash 走了 `sparse_mode=4` 而非 `0` |
| `_maybe_add_hidden_state` | `deepseek_v4.py` | DeepSeek-V4 的 `hc_post` 已合并残差，`hidden_states` 单独即可 |
| `target_hidden_size` | `patch_qwen3_dflash.py` | DeepSeek-V4 的 hc_mult=4，fc 输入需 ×4 |
| 3D aux flatten | `model_runner_v1.py` | DeepSeek-V4 的 aux 是 3D，需 flatten 后给 fc |
| KV cache 处理 | `patch_kv_cache_utils.py` | draft 层是标准 attention，不是 MLA，需单独处理 |