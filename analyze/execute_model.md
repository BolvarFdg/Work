代码内容与之前一致，行号略有偏移（从1927变为1904）。以下是重新对齐行号后的详细解析。

## `execute_model()` 逐段详解

**位置**: `vllm-ascend/vllm_ascend/worker/model_runner_v1.py:1904`

### 输入与返回值

```
输入:
  scheduler_output: SchedulerOutput       — 来自Scheduler，描述本step调度哪些请求、各请求分配多少token、KV cache block分配等
  intermediate_tensors: IntermediateTensors | None — 来自上一PP rank的中间张量（仅非首PP rank有值）

返回值 (三种可能):
  1. None                         — async scheduling模式，前向完成但采样延迟到sample_tokens()，状态存入self.execute_model_state
  2. IntermediateTensors          — 非最后PP rank，返回中间hidden_states给下一PP rank
  3. EMPTY_MODEL_RUNNER_OUTPUT    — 无请求调度时的空输出
```

---

### 1. 清理与初始化 (line 1909-1928)

```python
# 1909-1915: 如果启用了routed experts追踪，清理上一step的缓冲区
if self.vllm_config.model_config.enable_return_routed_experts:
    if vllm_version_is("0.21.0"):
        capturer = get_global_experts_capturer()
        if capturer is not None:
            capturer.finalize_pending_copy()    # 完成上一步未完成的D2H拷贝
    elif self.routed_experts_initialized:
        self.routed_experts_capturer.clear_buffer()

# 1917-1926: 如果启用了profiling计时
if self.ascend_config.profiling_chunk_config.need_timing:
    if getattr(scheduler_output, "disable_profiling_timing", False):
        self.ascend_config.profiling_chunk_config.need_timing = False  # 调度器通知停止计时
    else:
        self._sync_device()                 # 同步NPU，确保计时起点准确
        self._execution_start_time = time.perf_counter()

# 1927-1928: 状态检查，防止execute_model被重复调用
# async scheduling要求 execute_model→sample_tokens 严格配对
if self.execute_model_state is not None:
    raise RuntimeError("State error: sample_tokens() must be called after execute_model() returns None.")
```

**关键变量**: `self.execute_model_state` — `ExecuteModelState`对象，存储前向结果给`sample_tokens`使用

---

### 2. scheduler_output 深拷贝保护 (line 1933-1965)

```python
# 1933-1945: ngram_gpu投机解码需要修改scheduler_output，用replace避免影响engine core进程的原始对象
if self.speculative_config and self.speculative_config.use_ngram_gpu():
    num_scheduled_tokens_copy = scheduler_output.num_scheduled_tokens.copy()
    spec_decode_tokens_copy = scheduler_output.scheduled_spec_decode_tokens.copy()
    scheduler_output = replace(scheduler_output, ...)  # 浅拷贝替换可变字段

# 1955-1965: async scheduling + spec decode 或 PCP + 多模态时，需要deepcopy
# 原因: _update_states会修改scheduler_output，而async scheduling下engine core可能还在读原始对象
if (async_scheduling and num_spec_tokens and draft_token_ids is None) or (pcp and mm_inputs):
    scheduler_output = deepcopy(scheduler_output)

num_scheduled_tokens = scheduler_output.total_num_scheduled_tokens  # 本step总token数
```

---

### 3. 输入准备阶段 (line 1967-2205, `with record_function("prepare input")`)

#### 3a. 异步调度状态修正 (line 1975-1986)

```python
# 修正上一步被discard的请求的spec decode状态
if self.use_async_scheduling and self.num_spec_tokens and self.input_batch.prev_req_id_to_index is not None:
    for req_id in scheduler_output.scheduled_cached_reqs.req_ids:
        if req_id not in self.input_batch.prev_req_id_to_index:
            # 请求已被丢弃，重置prev_num_draft_len避免_update_states中KeyError
            if (req_state := self.requests.get(req_id)) is not None and req_state.prev_num_draft_len:
                req_state.prev_num_draft_len = 0
```

#### 3b. 更新batch状态 (line 1988-1991)

```python
deferred_state_corrections_fn = self._update_states(scheduler_output)
```
- 将scheduler_output中的新请求/已缓存请求/已删除请求同步到 `self.input_batch`
- 更新 `num_computed_tokens`、`block_table`、`slot_mapping` 等
- 返回 `deferred_state_corrections_fn`：延迟修正函数，async scheduling下用于修正上一步的spec decode状态

#### 3c. 提前退出检查 (line 2002-2017)

```python
if not num_scheduled_tokens:          # 无token需要调度
    if external_launcher and dp > 1:
        self._dummy_run(1)           # DP同步需要dummy run
    if not has_kv_transfer_group():
        return EMPTY_MODEL_RUNNER_OUTPUT   # 返回空结果
    return self.kv_connector_no_forward(...)  # KV transfer场景
```

#### 3d. 准备输入张量 (line 2025-2039)

```python
num_reqs = self.input_batch.num_reqs                         # 当前batch请求数
req_ids = self.input_batch.req_ids                            # 请求ID列表
tokens = [scheduler_output.num_scheduled_tokens[i] for i in req_ids]  # 每请求本step token数
num_scheduled_tokens_np = np.array(tokens, dtype=np.int32)   # numpy数组方便计算
max_num_scheduled_tokens = int(num_scheduled_tokens_np.max())  # 最大单请求token数

(logits_indices,              # [num_reqs] int tensor — 哪些位置需要计算logits（通常每请求最后一个token）
 spec_decode_metadata,        # 投推测码元数据（draft token info, num_draft_tokens）
 total_num_scheduled_tokens,  # 含spec decode的总token数，可能 > num_scheduled_tokens
 num_scheduled_tokens_compressed_list,  # DSv4压缩后的token数列表
) = self._prepare_inputs(scheduler_output, num_scheduled_tokens_np)
```

**关键变量**:
- `logits_indices`: 指向hidden_states中需要计算logits的token位置
- `spec_decode_metadata`: 包含draft token IDs等，用于rejection sampling
- `total_num_scheduled_tokens`: 含spec decode追加的draft tokens

#### 3e. 确定batch执行模式 (line 2054-2089)

```python
(cudagraph_mode,        # NONE / FULL / FULL_DECODE_ONLY — 是否用ACLgraph
 batch_desc,            # BatchDescriptor: num_tokens, num_reqs (padding后的)
 should_ubatch,         # 是否需要micro-batching (DBO)
 num_tokens_across_dp,  # DP各rank的token数（用于DP同步）
 cudagraph_stats,       # cudagraph统计信息
) = self._determine_batch_execution_and_padding(
    num_tokens=num_tokens_unpadded,           # 未padding的真实token数
    num_reqs=num_reqs,
    num_scheduled_tokens_np=num_scheduled_tokens_np,
    max_query_len=max_num_scheduled_tokens,
    use_cascade_attn=cascade_attn_prefix_lens is not None,
    force_eager=self.model_config.enforce_eager,
    num_encoder_reqs=len(scheduler_output.scheduled_encoder_inputs),
)

num_tokens_padded = batch_desc.num_tokens       # padding到cudagraph固定尺寸的token数
num_reqs_padded = batch_desc.num_reqs or num_reqs
ubatch_slices, ubatch_slices_padded = maybe_create_ubatch_slices(...)  # micro-batch切片
pad_attn = cudagraph_mode == CUDAGraphMode.FULL  # attention是否需要padding
```

**关键变量**:
- `num_tokens_padded`: padding到cudagraph固定尺寸的token数，可能 > `num_tokens_unpadded`
- `cudagraph_mode`: 决定是否走ACL graph捕获/replay路径

#### 3f. Mamba预处理 (line 2095-2136)

```python
if self.cache_config.mamba_cache_mode == "align":
    # 先执行延迟修正（因为preprocess_mamba需要读CPU侧的num_computed_tokens）
    if deferred_state_corrections_fn:
        deferred_state_corrections_fn()
        deferred_state_corrections_fn = None
    # Mamba/RWKV等SSM模型的状态拷贝预处理
    mamba_utils.preprocess_mamba(
        scheduler_output, self.kv_cache_config, self.cache_config,
        self.mamba_state_idx, self.input_batch, self.requests,
        self.compilation_config.static_forward_context,
        self.model.get_mamba_state_copy_func(), preprocess_bufs,
    )
    # 同步num_accepted_tokens到GPU
    self.num_accepted_tokens.np[:num_reqs] = self.input_batch.num_accepted_tokens_cpu[:num_reqs]
    self.num_accepted_tokens.copy_to_gpu(num_reqs)
```

#### 3g. DSA压缩位置计算 (line 2137-2148) — DSv4专属

```python
if self.use_compress:     # DeepSeek-V4特有
    # 先执行延迟修正
    if deferred_state_corrections_fn:
        deferred_state_corrections_fn()
        deferred_state_corrections_fn = None
    num_reqs = self.input_batch.num_reqs
    # 计算每个token在压缩KV cache中的绝对位置
    req_indices = np.repeat(self.arange_np[:num_reqs], num_scheduled_tokens_np)
    dsa_positions_np = self._dsa_positions_np_buf[:total_num_scheduled_tokens]
    # dsa_position = num_computed_tokens + query_pos（每个token的绝对序列位置）
    np.add(
        self.input_batch.num_computed_tokens_cpu[req_indices],  # 每请求已计算token数
        self.query_pos.np[:total_num_scheduled_tokens],        # 本step内的相对位置
        out=dsa_positions_np,                                    # 输出: 每token绝对位置
    )
```

**关键变量**: `dsa_positions_np` — `[total_num_scheduled_tokens]` int64，用于DSv4计算压缩slot mapping和RoPE位置

#### 3h. 构建attention metadata (line 2165-2180)

```python
(attn_metadata,                       # dict[str, AttentionMetadata] — 每层一个metadata
 spec_decode_common_attn_metadata,    # 投推测码的公共attn metadata
) = self._build_attention_metadata(
    num_tokens=num_tokens_unpadded,
    num_tokens_padded=num_tokens_padded,
    num_reqs=num_reqs,
    num_reqs_padded=num_reqs_padded,
    max_query_len=max_num_scheduled_tokens,
    ubatch_slices=ubatch_slices_attn,
    logits_indices=logits_indices,
    use_spec_decode=use_spec_decode,
    num_scheduled_tokens=scheduler_output.num_scheduled_tokens,
    num_scheduled_tokens_np=num_scheduled_tokens_np,
    cascade_attn_prefix_lens=cascade_attn_prefix_lens,
    num_scheduled_tokens_compressed_list=num_scheduled_tokens_compressed_list,  # DSv4压缩token数
)
```

**关键变量**: `attn_metadata` — dict，key是层名，value是该层的metadata对象（如DSA metadata、SWA metadata、indexer metadata）。model forward时各层通过 `get_forward_context()` 读取。

#### 3i. 预处理获取模型输入 (line 2189-2205)

```python
(input_ids,          # [num_tokens_padded] int tensor — 本step要处理的token IDs
 inputs_embeds,      # [num_tokens_padded, hidden] tensor — 多模态嵌入（非None时替代input_ids）
 positions,          # [num_tokens_padded] int tensor — 每个token的绝对位置
 intermediate_tensors,  # IntermediateTensors — PP中间结果
 model_kwargs,       # dict — 额外模型参数
 ec_connector_output,    # EC connector输出
) = self._preprocess(scheduler_output, num_tokens_padded, intermediate_tensors)

update_cos_sin(positions)   # 根据positions更新全局RoPE cos/sin表
```

**关键变量**:
- `input_ids`: 本step所有请求的token ID拼接序列
- `positions`: 每个token在序列中的绝对位置（用于RoPE和KV cache slot计算）

---

### 4. 前向计算 (line 2229-2258)

```python
clear_kv_metadata = self.speculative_config is None

with (
    record_function_or_nullcontext("forward"),
    # 设置forward context: 将attn_metadata、cudagraph_mode等注入全局上下文
    # model forward期间各层通过 get_forward_context() 读取这些信息
    set_ascend_forward_context(
        attn_metadata,                              # 注意力元数据
        self.vllm_config,
        num_tokens=num_tokens_padded,               # padding后token数
        num_tokens_across_dp=num_tokens_across_dp,   # DP同步用
        aclgraph_runtime_mode=cudagraph_mode,        # 是否走ACL graph
        batch_descriptor=batch_desc,
        num_actual_tokens=scheduler_output.total_num_scheduled_tokens,
        model_instance=self.model,
        max_tokens_across_pcp=...,                   # PCP跨rank最大token数
        skip_compiled=has_encoder_input,             # encoder-decoder首步跳过编译
        has_sinks=self._has_sinks,
        input_ids=input_ids,
    ),
    # KV connector输出（投机解码时延迟finalize）
    self.maybe_get_kv_connector_output(
        scheduler_output,
        defer_finalize=not clear_kv_metadata,
    ) as kv_connector_output,
):
    if self.cache_config.mamba_cache_mode == "align":
        mamba_utils.do_mamba_copy_block(preprocess_bufs)  # Mamba状态拷贝到GPU
    # 执行模型前向: self.model(input_ids, positions, ...)
    # = 所有decoder层的完整forward → 返回 hidden_states
    hidden_states = self._model_forward(
        num_tokens_padded, input_ids, positions, intermediate_tensors, inputs_embeds, **model_kwargs
    )
```

**关键**: `_model_forward` (line 2766) 内部调用 `self.model(input_ids=..., positions=..., ...)`，即模型的完整forward，遍历所有decoder层。

---

### 5. 后处理与logits计算 (line 2259-2312)

```python
with record_function_or_nullcontext("post process"):
    aux_hidden_states = None
    if self.use_aux_hidden_state_outputs:       # EAGLE3需要中间层hidden states
        hidden_states, aux_hidden_states = hidden_states   # 拆分返回

    if self.pcp_size > 1:                        # PCP: allgather后恢复原始顺序
        hidden_states = self.pcp_manager.get_restore_hidden_states(hidden_states)
        if aux_hidden_states is not None:
            aux_hidden_states = [self.pcp_manager.get_restore_hidden_states(h) for h in aux_hidden_states]

    if not self.broadcast_pp_output:
        # 常见情况
        if not get_pp_group().is_last_rank:
            # 非最后PP rank: 返回中间张量给下一PP rank
            assert isinstance(hidden_states, IntermediateTensors)
            hidden_states.kv_connector_output = kv_connector_output
            return hidden_states                        # ← 返回 IntermediateTensors

        if self.is_pooling_model:
            output = self._pool(...)
            return output                              # ← 返回 pooling output

        # 最后PP rank: 计算logits
        sample_hidden_states = hidden_states[logits_indices]  # 取每请求最后一个token的hidden state
        logits = self.model.compute_logits(sample_hidden_states)  # [num_reqs, vocab_size]
    else:
        # 罕见情况: PP输出需要broadcast
        ...
```

**关键变量**:
- `hidden_states`: `[num_tokens_padded, hidden_size]` — 所有token的最后一层输出
- `sample_hidden_states`: `[num_reqs, hidden_size]` — 仅需采样的token的hidden states
- `logits`: `[num_reqs, vocab_size]` — 仅对需采样的token计算logits
- `aux_hidden_states`: `list[Tensor]` — EAGLE3需要的中间层hidden states

---

### 6. 存储状态并返回 (line 2315-2335)

```python
# 将所有中间状态存入 execute_model_state，供后续 sample_tokens() 使用
self.execute_model_state = ExecuteModelState(
    scheduler_output,               # 调度输出（sample_tokens需要用来bookkeeping）
    logits,                         # [num_reqs, vocab_size]
    spec_decode_metadata,           # 投推测码元数据
    spec_decode_common_attn_metadata,
    hidden_states,                  # 完整hidden states（drafter需要）
    sample_hidden_states,           # 仅logits位置的hidden states
    aux_hidden_states,              # EAGLE3中间层
    attn_metadata,                  # attention metadata
    positions,                      # 位置信息
    ec_connector_output,
    cudagraph_stats,
    batch_desc,
)
self.kv_connector_output = kv_connector_output

# 执行延迟状态修正（async scheduling下修正上一步的spec decode结果）
if deferred_state_corrections_fn:
    deferred_state_corrections_fn()

# async scheduling下返回None
# Engine Core收到None后会调用 sample_tokens()
return None
```

---

### 数据流总结

```
SchedulerOutput (来自Scheduler)
  │  - 哪些请求、每请求多少token、KV cache block分配
  │  - spec decode draft tokens
  │  - 新请求/已删除请求
  │
  ▼
_update_states()  →  input_batch (持久化batch状态)
  │                   - req_ids, num_computed_tokens, block_table
  │
  ▼
_prepare_inputs()  →  positions, slot_mapping, logits_indices
  │                     spec_decode_metadata, dsa_positions(DSv4)
  │
  ▼
_determine_batch_execution_and_padding()  →  cudagraph_mode, batch_desc
  │                                            num_tokens_padded, num_tokens_across_dp
  │
  ▼
_build_attention_metadata()  →  attn_metadata (dict[层名→metadata])
  │                                - SWA metadata, CSA metadata, indexer metadata
  │
  ▼
_preprocess()  →  input_ids, positions, inputs_embeds
  │
  ▼
update_cos_sin(positions)  →  全局RoPE cos/sin表
  │
  ▼
set_ascend_forward_context(attn_metadata, ...)  ← 注入全局上下文
  │
  ▼
_model_forward()  →  hidden_states [num_tokens_padded, hidden_size]
  │                     (所有decoder层完整forward)
  │
  ▼
compute_logits(hidden_states[logits_indices])  →  logits [num_reqs, vocab]
  │
  ▼
存入 self.execute_model_state, return None
  │
  ▼ (后续由 sample_tokens() 取出)
_sample(logits)  →  sampled_token_ids  →  ModelRunnerOutput
```