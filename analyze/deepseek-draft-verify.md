## 1. 小模型推理出 draft_token

**入口**：`vllm-ascend/vllm_ascend/worker/model_runner_v1.py:1895`
```python
draft_token_ids = self.drafter._propose(
    target_token_ids=..., target_hidden_states=..., ...
)
```

**核心执行**：`vllm-ascend/vllm_ascend/spec_decode/llm_base_proposer.py`

| 步骤 | 行号 | 代码 |
|------|------|------|
| `_propose` 定义 | 681 | 接收 target hidden states，调用 `combine_hidden_states` 投影 |
| 绑定执行体 | 1032 | `run_draft = partial(self._runnable, **model_inputs)` |
| 执行推理 | 1036 | `draft_token_ids = run_draft()` |
| `_run_merged_draft` 定义 | 1080 | DFlash 走 `build_model_inputs_first_pass`（写入 KV cache）+ `self.model(**model_kwargs)`（draft 前向） |
| 采样 hidden states | 1155 | `sample_hidden_states = last_hidden_states[token_indices_to_sample]` |
| **生成 token** | 1158 | `draft_token_ids = self.compute_draft_token_ids(sample_hidden_states)` |
| `compute_draft_token_ids` | 1042 | `logits = self.model.logits_processor(self.model.lm_head, hidden_states)` → `greedy_sample(logits)` |
| `greedy_sample`（TP argmax） | `vllm_ascend/sample/rejection_sampler.py:201` | 跨 TP rank all_gather 后全局 argmax |

---

## 2. 大模型校验小模型 token

### 入口
`vllm-ascend/vllm_ascend/worker/model_runner_v1.py:2588`
```python
sampler_output = self.rejection_sampler(
    spec_decode_metadata,  # 包含 draft_token_ids
    None,                   # draft_probs
    logits,                 # 大模型输出的 logits
    sampling_metadata,
)
```

### 过程
`vllm-ascend/vllm_ascend/sample/rejection_sampler.py`

| 步骤 | 行号 | 说明 |
|------|------|------|
| `forward` 定义 | 98 | 接收 metadata + logits |
| 采 bonus token | 138-150 | 大模型对 bonus 位置采样，保证至少产出 1 个新 token |
| 取 target logits | 155 | `raw_target_logits = logits[target_logits_indices]` — 大模型对 draft 位置的预测 |
| **执行校验** | 172 | `rejection_sample(metadata.draft_token_ids, ..., target_logits, bonus_token_ids, ...)` |
| `rejection_sample` 定义 | 289 | 核心校验逻辑 |
| 贪心路径 | 404-443 | `target_argmax = greedy_sample(target_logits)` → 逐位置比较 draft token 与 target argmax，相等接受，不等拒绝 |
| 随机路径 | 447-562 | 用概率比较 draft_probs vs target_probs，按均匀随机数决定接受/拒绝 |
| 输出 | 374-379 | `output_token_ids [B, K+1]`，**拒绝位置填 `PLACEHOLDER_TOKEN_ID` (-1)** |

### 结果反馈

| 步骤 | 文件 | 行号 | 说明 |
|------|------|------|------|
| 过滤 -1 | `vllm/v1/sample/rejection_sampler.py` | 247 | `parse_output`：`valid_mask = (token_ids != -1)` → 过滤出接受 token |
| 写回 input_batch | `model_runner_v1.py` | 2598 | `_bookkeeping_sync`：解析结果，写回 `token_ids_cpu`、`num_tokens` |
| 封装返回 | `model_runner_v1.py` | 2513 | `ModelRunnerOutput(sampled_token_ids=valid_sampled_token_ids)` |
| **scheduler 消费** | `vllm/v1/core/sched/scheduler.py` | 1373 | `num_accepted = len(generated_token_ids) - 1` |
| 回退计算 | 同上 | 1381 | `request.num_computed_tokens -= num_rejected`（拒绝的 token 视为未计算） |
| 统计指标 | 同上 | 1386 | `make_spec_decoding_stats(num_draft_tokens, num_accepted_tokens)` |

### 完整数据流

```
drafter._propose → _run_merged_draft → model forward → compute_draft_token_ids
    → draft_token_ids [B, K]
        → 塞入 spec_decode_metadata
            → 大模型前向 → logits
                → rejection_sampler(metadata, logits)          [model_runner_v1.py:2588]
                    → rejection_sample()                       [rejection_sampler.py:289]
                        → 逐位置比较: draft_token == target_argmax?
                            → 相等: 接受 (保留 token id)
                            → 不等: 拒绝 (填 -1)
                        → output_token_ids [B, K+1]
                    → parse_output() 过滤 -1                    [rejection_sampler.py:247]
                        → valid_sampled_token_ids
                            → _bookkeeping_sync 写回 input_batch
                                → ModelRunnerOutput
                                    → scheduler.update_from_output()
                                        → num_accepted / num_rejected
                                        → 回退 num_computed_tokens
                                        → 记录 spec_decode 统计指标
```