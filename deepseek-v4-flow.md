## DeepSeek-V4 推理完整流程

### 1. API 请求入口

```
POST /v1/chat/completions
  │
  ├─ vllm/entrypoints/openai/chat_completion/api_router.py:53  create_chat_completion
  ├─ vllm/entrypoints/openai/chat_completion/serving.py:228     ServingChat.create_chat_completion
  ├─ vllm/v1/engine/async_llm.py:524                           AsyncLLM.generate
  ├─ vllm/v1/engine/core_client.py:1090                         AsyncMPClient.add_request_async
  └─ vllm/v1/engine/core.py:337                                 EngineCore.add_request（加入 scheduler）
```

### 2. Scheduler 调度

```
vllm/v1/engine/core.py:428  EngineCore.step（核心循环）
  │
  ├─ vllm/v1/core/sched/scheduler.py:329  Scheduler.schedule
  │    组装 batch：先排 RUNNING，再排 WAITING
  │    处理 chunked prefill / prefix cache / spec decode
  │    产出 SchedulerOutput
  │
  ├─ model_executor.execute_model(scheduler_output)  → 提交给 worker
  │
  └─ vllm/v1/core/sched/scheduler.py:1283  Scheduler.update_from_output
       更新 request 状态（num_computed_tokens 等）
```

### 3. Worker 执行

```
vllm-ascend/worker/worker.py:603       NPUWorker.execute_model
  │
  └─ vllm-ascend/worker/model_runner_v1.py:1956  NPUModelRunner.execute_model
       │
       ├─ :762   _prepare_inputs（组装 batch、input_ids、positions、spec_decode_metadata）
       ├─ :1406  _preprocess（取 input_ids/positions/intermediate_tensors）
       ├─ :2209  _build_attention_metadata
       ├─ :2277  set_ascend_forward_context（注入 attn_metadata、MoE 通信、SP 配置）
       ├─ :2300  _model_forward（★ 模型前向，见步骤 4-6）
       ├─ :2336  compute_logits（LogitsProcessor(lm_head, hidden_states)）
       │         execute_model 返回 None
       │
       └─ :2382  sample_tokens（由 EngineCore 调用）
              ├─ :2445  propose_draft_token_ids（如果有 spec decode）
              ├─ :2576  _sample（采样，见步骤 7）
              └─ 返回 ModelRunnerOutput
```

### 4. Model Forward

```
vllm-ascend/models/deepseek_v4.py:1277  AscendDeepseekV4ForCausalLM.forward
  │
  └─ DeepseekV4Model.forward (:1108)
       │
       ├─ :1119  embed_input_ids → [num_tokens, hidden_size]
       │
       ├─ :1139  unsqueeze(1).repeat(1, hc_mult, 1) → [num_tokens, hc_mult, hidden_size]
       │          ★ 2D → 3D 扩展（HC 通道扩展）
       │
       ├─ :1141  for layer in layers:                   ★ 逐层处理（见步骤 5）
       │          │  _maybe_add_hidden_state (如果收集 aux)
       │          └─ hidden_states, residual = layer(positions, hidden_states, residual, ...)
       │
       ├─ :1167  _mtp_hidden_buffer.copy(hidden_states.flatten(1))
       │          ★ 缓存 pre-hc_head 残差（供 MTP drafter 用）
       │
       ├─ :1176  hc_head(hidden_states)  → [num_tokens, hidden_size]
       │          ★ 3D → 2D 压缩（RMS + sigmoid 门控 + 加权求和）
       │
       ├─ :1178  norm(hidden_states) → RMSNorm
       │
       └─ 返回 hidden_states（或 (hidden_states, aux_hidden_states)）
```

### 5. Decoder Layer 内部

```
vllm-ascend/models/deepseek_v4.py:974  DeepseekV2DecoderLayer.forward
  │
  ├─ :981  residual = hidden_states.clone()           ① 保存输入
  ├─ :982  hc_pre(hidden_states, hc_attn_fn, ...)     ② HC 前处理（Sinkhorn 归一化，分通道）
  ├─ :983  input_layernorm(hidden_states)              ③ RMSNorm
  ├─ :985  self_attn(positions, hidden_states, ...)    ④ DSA 注意力（见步骤 6）
  ├─ :986  hc_post(hidden_states, residual, ...)       ⑤ HC 后处理（合并通道 + residual）
  │
  ├─ :987  residual = hidden_states.clone()            ⑥ 保存中间状态
  ├─ :988  hc_pre(hidden_states, hc_ffn_fn, ...)       ⑦ HC 前处理
  ├─ :989  post_attention_layernorm(hidden_states)     ⑧ RMSNorm
  ├─ :990  mlp(hidden_states)                           ⑨ MoE（见下方）
  └─ :991  hc_post(hidden_states, residual, ...)        ⑩ HC 后处理
```

**MoE 内部** (`:452` `DeepseekV4MoE.forward`)：

```
  ├─ router_logits = Linear(hidden_states, gate.weight)   ① 路由
  ├─ FusedMoE(hidden_states, router_logits)                 ② top-k expert 选择 + expert 计算
  │    含: softmax 路由 → top-k → grouped GEMM → 合并
  ├─ muls_add_triton(final, shared, scaling_factor)        ③ 合并 shared expert
  └─ all_gather (如果 SP) / all_reduce (如果 TP)            ④ 跨卡合并
```

### 6. DSA Attention 内部

```
vllm-ascend/models/deepseek_v4.py:894  DeepseekV4Attention.forward
  │
  └─ vllm-ascend/ops/dsa.py:157  AscendDeepseekSparseAttention.forward
       │
       └─ torch.ops.vllm.dsa_forward (dsa.py:178)
            │
            └─ vllm-ascend/attention/dsa_v1.py:1526  AscendDSAImpl.forward
                 │
                 ├─ 拆分 prefill / decode
                 │
                 └─ _forward_prefill (:1724)
                      │
                      ① MLA Prolog (:1763-1830)
                      │  ├─ q_a = wq_a(hidden_states)           Q 第一级投影
                      │  ├─ qr = q_norm(q_a)                     RMSNorm
                      │  ├─ q = wq_b(qr)                        Q 第二级投影 → [N, heads, head_dim]
                      │  ├─ q = apply_dsa_q_rms(q)              per-head RMSNorm
                      │  ├─ partial_rotary_mul(q, cos, sin)     partial RoPE
                      │  ├─ kv = wkv(hidden_states)             KV 投影
                      │  ├─ kv = kv_norm(kv)                    RMSNorm
                      │  ├─ partial_rotary_mul(kv, cos, sin)   partial RoPE
                      │  └─ dsa_kv_compress_scatter(swa_kv_cache, kv, slot_mapping)
                      │                                       写入 SWA KV cache（近处全精度）
                      │
                      ② Indexer (:1862-1975，仅 compress_ratio==4)
                      │  ├─ weights = weights_proj(hidden_states)   权重投影
                      │  ├─ q_quant = indexer_quantize_query(q)     Q 量化
                      │  └─ npu_quant_lightning_indexer(q_quant, indexer_k_cache, ...)
                      │                                       量化 Q·K 点积 → 选 top-k 稀疏索引
                      │                                       输出 compress_topk_idxs
                      │
                      ③ Compressor (:1904-1943)
                      │  ├─ compressed_kv = torch.ops._C_ascend.compressor(
                      │  │    hidden_states, wkv, wgate, state_cache, ape, norm, sin, cos, ...)
                      │  │    内部: RMSNorm → KV投影 → RoPE → 读 state_cache → 门控混合 → 写回 → 提取
                      │  └─ dsa_kv_compress_scatter(compress_kv_cache, compressed_kv, ...)
                      │                                       写入压缩 KV cache（中处压缩）
                      │
                      ④ 三级 Sparse Attention (:1984-2004)
                      │  └─ attn_op(q, 
                      │       ori_kv=swa_kv_cache,              近处: 滑动窗口全精度 KV
                      │       cmp_kv=compress_kv_cache,          中处: 4x 压缩 KV
                      │       cmp_sparse_indices=topk_idxs,     远处: 128x 压缩 KV 的稀疏索引
                      │       ori_mask_mode=4,                  SWA 滑动窗口 mask
                      │       cmp_mask_mode=3,                  causal mask
                      │       sinks=attn_sink,                  attention sink
                      │       softmax_scale=head_dim^-0.5, ...)
                      │    内部: QK^T → scale → softmax(+sinks) → AV（融合算子）
                      │
                      ⑤ O 投影 (:1579-1623)
                      │  ├─ partial_rotary_mul(o_proj_input, cos, sin)
                      │  ├─ wo_a (npu_transpose_quant_batchmatmul)
                      │  └─ wo_b
                      │
                      └─ 返回 attn_output
```

### 7. Sampling

```
vllm-ascend/worker/model_runner_v1.py:2576  _sample
  │
  ├─ 无 spec decode（普通采样）:
  │    vllm-ascend/sample/sampler.py:45  AscendSampler
  │    ├─ greedy_sample (:104)  → TP all_gather argmax
  │    └─ topK/topP (:127)     → AscendTopKTopPSampler
  │
  └─ 有 spec decode（投机采样）:
       ① 先生成 draft token:
          model_runner_v1.py:1655  propose_draft_token_ids
          └─ drafter._propose(llm_base_proposer.py:681)
               ├─ combine_hidden_states  (fc 投影)
               ├─ _run_merged_draft     (drafter forward)
               └─ compute_draft_token_ids (logits → argmax)

       ② 再用 target logits 校验:
          vllm-ascend/sample/rejection_sampler.py:98  AscendRejectionSampler.forward
           ├─ :139  bonus 采样（保证至少 1 个新 token）
           ├─ :172  rejection_sample(draft_token_ids, target_logits, ...)
           │         逐位置比较: draft == target_argmax?
           │         相等 → 接受（保留 token id）
           │         不等 → 拒绝（填 -1）
           └─ 返回 output_token_ids [B, K+1]
```

### 8. Output 返回

```
vllm-ascend/worker/model_runner_v1.py:2382  sample_tokens 返回 ModelRunnerOutput
  │
  ├─ vllm/v1/engine/core.py:446-448    EngineCore.step 回收 future
  ├─ vllm/v1/core/sched/scheduler.py:1283  Scheduler.update_from_output
  │    ├─ 解析接受/拒绝 token
  │    ├─ 更新 num_computed_tokens（拒绝的回退）
  │    └─ 记录 spec decode 统计指标
  │
  ├─ vllm/v1/engine/core.py:457       EngineCore.step 返回 EngineCoreOutputs
  │
  ├─ vllm/v1/engine/core_client.py:1022  AsyncMPClient.get_output_async（IPC 回送）
  │
  ├─ vllm/v1/engine/output_processor.py:576  OutputProcessor.process_outputs
  │    ├─ detokenize（token_ids → text）
  │    └─ 组装 RequestOutput
  │
  ├─ vllm/v1/engine/async_llm.py:576   AsyncLLM.generate yield RequestOutput
  │
  └─ vllm/entrypoints/openai/chat_completion/serving.py:228  返回 StreamingResponse
```

### 全流程一句话

```
API请求 → EngineCore.step → Scheduler.schedule(组batch)
  → NPUWorker.execute_model → _prepare_inputs → set_ascend_forward_context
    → AscendDeepseekV4ForCausalLM.forward
      → embed → repeat(hc_mult) → 逐层[hc_pre → layernorm → DSA注意力 → hc_post → hc_pre → layernorm → MoE → hc_post]
        → DSA内部: MLA prolog(Q/KV投影) → Indexer(选top-k) → Compressor(时序压缩) → 三级attention(SWA+压缩+稀疏)
      → hc_head(压缩回2D) → norm
    → compute_logits
  → sample_tokens → AscendSampler(普通) 或 AscendRejectionSampler(投机)
  → Scheduler.update_from_output → EngineCoreOutputs → OutputProcessor(detokenize) → API Response
```