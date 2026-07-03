## DeepSeek-V4 在 vllm 和 vllm-ascend 中的代码实现梳理

### 一、整体架构概述

DeepSeek-V4 的注意力架构是一种**混合稀疏注意力**（DSA），核心思想是将长序列的 KV 压缩后做稀疏检索，短序列部分用滑动窗口（SWA）做局部注意力。根据 `compress_ratios` 配置，每层分为三种类型：

| 层类型 | compress_ratio | 作用 | 关键组件 |
|--------|----------------|------|----------|
| **SWA-only** | ≤1 | 纯滑动窗口，只看最近 `window_size` 个 token | `DeepseekV4SWACache` |
| **C4A** (CSA) | 4 | 4倍压缩 + indexer稀疏检索 | Indexer + Compressor + SWA |
| **C128A** (HCA) | 128 | 128倍压缩，无indexer，topk直接预计算 | Compressor + SWA |

---

### 二、核心组件详解

#### 1. MLA (Multi-head Latent Attention) — 低秩压缩注意力

**vllm 实现** (`vllm/model_executor/layers/deepseek_v4_attention.py:113`)

MLA 的核心是：Q 和 KV 都先压缩到低秩 latent 空间，再做注意力计算，最后再投影回原始空间：

```
hidden_states -> fused_wqa_wkv -> [q_lora=1536, kv_lora=512] -> q_norm/kv_norm
  -> wq_b(q) -> [n_heads, head_dim=512] -> RoPE -> attention
  -> wo_a(LoRA输出) -> wo_b -> output
```

**关键融合操作**（vllm CUDA）：
- `fused_q_kv_rmsnorm` (`deepseek_v4_ops/fused_qk_rmsnorm.py`): 一个 kernel 同时做 Q 和 KV 的 RMSNorm
- `fused_qnorm_rope_kv_insert`: Q-head-RMSNorm + Q-RoPE | KV-RoPE + FP8量化 + SWA cache写入
- `fused_inv_rope_fp8_quant` (`deepseek_v4_ops/fused_inv_rope_fp8_quant.py`): 对 attention 输出做**逆RoPE** + FP8量化，为 `wo_a` 的 FP8 einsum 做准备
- 4路 CUDA stream 并行 GEMM: `wqa_wkv`(最重) | compressor_kv | indexer_weight_proj | indexer_compressor_kv

**vllm-ascend 实现** (`vllm_ascend/attention/dsa_v1.py:1378`, `sfa_v1.py:390`)

Ascend 上的 MLA 适配（`AscendDSAImpl` / `AscendSFAImpl`）：
- **CVLinearWrapper**: Vector核量化 + Cube核矩阵乘 分流并行
- **多流overlap** (`_mla_prolog_multistream`, dsa_v1.py:1691): 3阶段双流流水线
  - Part1: `q_quant[V] || kv_quant[V]`
  - Part2: `q_norm+q_b_quant[V] || kv_matmul[C]`
  - Part3: `q_b_matmul[C] || kv_norm+rope+scatter[AIV]`
- **MLAPO**: 融合 `q_a_layernorm + kv_a_layernorm + q_proj + kv_proj` 为单一算子
- **共享量化**: 当 wq_a 和 wkv 都是 W8A8 dynamic quant 时，对 hidden_states 只做一次 `npu_dynamic_quant`
- 输出投影: A5 用 `npu_dynamic_mx_quant` + `npu_transpose_quant_batchmatmul`; 其他用 `npu_transpose_batchmatmul`
- 权重拆分: `kv_b_proj` 拆为 `W_UV`(V上投影) 和 `W_UK_T`(K上投影转置)，支持 MLA absorb 模式

---

#### 2. SWA (Sliding Window Attention) — 滑动窗口注意力

**vllm 实现** (`vllm/v1/attention/backends/mla/sparse_swa.py:49`)

`DeepseekV4SWACache` 是一个 `nn.Module + AttentionLayerBase`：
- block_size 固定为 64（与 C4A KV block 共享物理张量）
- 返回 `SlidingWindowMLASpec`（alignment=576，FlashMLA要求）
- Backend: `DeepseekSparseSWABackend`，名称 `DEEPSEEK_SPARSE_SWA`
- FP8 KV cache shape: `(num_blocks, block_size, 584)` = 448 NoPE(FP8) + 128 RoPE(bf16) + 8 UE8M0 scale

**Decode 路径**:
- Triton kernel `_compute_swa_indices_and_lens_kernel` 为每个 token 计算 `swa_len` 和 `swa_indices`
- `swa_len = end_pos - start_pos`，其中 `start_pos = max(pos - window_size + 1, 0)`
- `swa_indices`: 通过 block_table 查表得到全局 slot ID

**vllm-ascend 实现** (`vllm_ascend/models/deepseek_v4.py:182`)

`AscendDeepseekV4SWACache`:
- A5 设备: dtype=`float8_e4m3fn`, `cached_head_size = head_dim + 128`（额外128字节padding）
- 其他设备: dtype=`bfloat16`
- block_size 由 `_dsv4_block_sizes()` 决定（32/64/128）
- 返回 `SlidingWindowMLASpec` with `model_version="deepseek_v4"`

---

#### 3. CSA (C4A — Compress-4-Attention) / Indexer 稀疏检索

**compress_ratio=4 的层使用 C4A**，特点是同时有 indexer（稀疏 top-k 选择器）和 compressor。

**Indexer** (`vllm/model_executor/layers/deepseek_v4_attention.py:1089`):
- `wq_b`: 从 `q_lora_rank=1536` 投影到 `n_head=64 * head_dim=128`
- `weights_proj`: 从 `hidden_size` 投影到 `n_head=64`（注意力权重）
- `k_norm`: LayerNorm on indexer KV
- `k_cache`: `DeepseekV4IndexerCache`（FP8 或 MXFP4 格式）
- `compressor`: 自己独立的 `DeepseekCompressor`（head_dim=128）
- `indexer_op`: `SparseAttnIndexer` 执行 top-k 选择

**Fused Indexer Q Kernel** (`deepseek_v4_ops/fused_indexer_q.py`):
- **FP8 路径**: RoPE + FP8量化，**q_scale 折叠到 weights**（`weights_out = weights * q_scale * softmax_scale * head_scale`）
- **MXFP4 路径**: RoPE + MXFP4量化（E2M1 2 nibbles/byte + ue8m0 block scale），**q_scale 不折叠**（per-block scale无法合并为单标量）
- CuteDSL 优化版本 (`fused_indexer_q_cutedsl.py`): 8线程 subwarp 处理，bf16x2 打包运算，支持 coarsen=1/4

**Indexer Cache Format** (`deepseek_v4_ops/cache_utils.py`):
| 格式 | 每token数据 | 每token scale |
|------|------------|--------------|
| FP8 (head=128) | 128 bytes FP8 | 4 bytes float32 |
| MXFP4 (head=128) | 64 bytes packed nibbles | 4 bytes ue8m0 |

**vllm-ascend 实现** (`vllm_ascend/models/deepseek_v4.py:146`, `dsa_v1.py`):
- `AscendDeepseekV4IndexerCache`: A5 强制 `float8_e4m3fn`，其他用 `torch.int8`
- **QLI (Quant Lightning Indexer)**: Ascend 自定义算子 `npu_quant_lightning_indexer` 用于 c4 sparse top-k 选择
- **Hadamard 旋转**: sfa_v1.py 中 c8 indexer 使用 Hadamard(128) 矩阵对 Q/K 做旋转后再量化
- DSA-CP 模式下: indexer 在 local token 上计算 top-k，KV cache 是全局的

---

#### 4. HCA (C128A — Compress-128-Attention) / 长程压缩注意力

**compress_ratio=128 的层**，不使用 indexer，top-k indices 直接预计算。

**vllm C128A top-k 元数据** (`vllm/v1/attention/backends/mla/flashmla_sparse.py:661`):
- `_build_c128a_topk_metadata_kernel`: 对每个 decode token，计算 `(position+1) // 128` = 可用压缩 KV 数量，通过 block_table 查表得到全局 slot ID
- 产生 `c128a_global_decode_topk_indices` 和 `c128a_decode_topk_lens`
- Prefill: 写入 local indices `[0, 1, ..., num_compressed-1]`
- 对齐要求: `_C128A_TOPK_ALIGNMENT = 128`

**vllm-ascend**: 在 `AscendDSAMetadataBuilder` 和 `AscendDSACPMetadataBuilder` 中同样为 c128 层预计算 top-k indices，使用 SAS metadata 构建。

---

#### 5. Compressor (KV 压缩器) — 统一的压缩机制

**vllm 实现** (`vllm/model_executor/layers/deepseek_compressor.py:177`)

`DeepseekCompressor` 是 C4A 和 C128A 共用的压缩模块：

```
hidden_states -> fused_wkv_wgate -> [kv_score, score_gate]
  -> _save_partial_states_kernel: 存入 state_cache (FP32)，加 APE (绝对位置编码)
  -> 仅在压缩边界 ((pos+1) % compress_ratio == 0) 时:
     -> _fused_kernel: softmax加权求和 -> RMSNorm -> RoPE -> FP8/MXFP4量化 -> 写入paged KV cache
```

**CompressorStateCache** (`deepseek_compressor.py:125`):
- dtype=float32，存储 compressor 的运行状态（KV + score）
- C4A: `sliding_window = 2*4 = 8`, block_size=4
- C128A: `sliding_window = 1*128 = 128`, block_size=8
- 返回 `SlidingWindowMLASpec`(alignment=576)

**三个融合 kernel** (`deepseek_v4_ops/fused_compress_quant_cache.py`):
| Kernel | Head dim | NoPE存储 | RoPE存储 | Scale格式 | Quant block |
|--------|---------|---------|---------|----------|------------|
| sparse_attn | 512 | 448 FP8 | 64 bf16 | 7 ue8m0 + 1 pad | 64 |
| indexer_fp8 | 128 | 全FP8 | 全FP8 | 1 float32 | 128 |
| indexer_mxfp4 | 128 | 全MXFP4 | 全MXFP4 | 4 ue8m0 bytes | 32 |

**vllm-ascend 实现** (`vllm_ascend/models/deepseek_v4.py:598`):
- `AscendCompressorStateCache`: 返回 `SlidingWindowMLASpec` with Ascend 的 `page_size_padded`
- A5 设备: `wkv`/`wgate` 不量化 (`quant_config=None`)，`RMSNorm` 用 float32
- RoPE 使用 `torch_npu.npu_rotary_mul` with `rotary_mode="interleave"`
- 压缩融合算子: `torch.ops._C_ascend.compressor` 替代 Triton kernel
- KV scatter: `npu_scatter_nd_update` / `npu_scatter_nd_update_v2`

---

#### 6. HC (Hybrid Computation / mHC) — 多流残差混合

**vllm 实现** (`vllm/model_executor/models/deepseek_v4.py:1095`)

Hybrid Computation (mHC) 将残差流扩展为 `hc_mult` 个并行流：
- 每层 decoder 在 attention 前后做 HC mixing
- `hc_fn`(权重矩阵), `hc_scale`, `hc_base` 参数
- Sinkhorn normalization: `hc_sinkhorn_iters`, `hc_eps`
- 自定义算子: `mhc_pre`, `mhc_fused_post_pre`, `mhc_post`
- 最终 `hc_head` 将多流collapse回单流

**vllm-ascend 实现** (`vllm_ascend/models/deepseek_v4.py:913`):
- 使用 Ascend 自定义算子 `npu_hc_pre` 和 `npu_hc_post` 替代 CUDA 的 mhc ops
- `hc_head` 用 sigmoid + linear 实现

---

#### 7. DSA-CP (DeepSeek Sparse Attention Context Parallel) — 序列并行

**vllm-ascend 实现** (`vllm_ascend/attention/context_parallel/dsa_cp.py:145`)

DSA-CP 将 token 序列按 TP rank 切分：
- `local_start = tp_rank * tokens_per_rank`
- **Q 计算**: 在 local hidden_states 上（local RoPE）
- **KV 计算**: 在 allgathered hidden_states 上（全量 RoPE + scatter 到 SWA cache）
- **Sparse attention**: local Q 对全量 KV cache（block_table 是全局的）
- **After attention**: 逆 RoPE → `all_to_all_single` 将 output heads 重新分配回各自 TP rank
- `attn_sink` 在 DSA-CP 模式下有全量 `num_heads`（不分片到 TP rank）

---

### 三、缓存体系总览

| 缓存类型 | vllm 格式 | vllm-ascend 格式 | 管理方式 |
|---------|-----------|-----------------|---------|
| **SWA KV Cache** | fp8_ds_mla (448 FP8 + 128 bf16 + 8 ue8m0) | A5: float8_e4m3fn (head_dim+128); 其他: bf16 | `DeepseekV4SWACache`/`AscendDeepseekV4SWACache` |
| **Compressed KV Cache** (C4A/C128A) | fp8_ds_mla (576B/token) | A5: float8_e4m3fn; 其他: int8 | `MLAAttentionSpec` with `compress_ratio` |
| **Indexer K Cache** | FP8 (128B+4B float32) 或 MXFP4 (64B+4B ue8m0) | A5: float8_e4m3fn; 其他: int8 | `DeepseekV4IndexerCache`/`AscendDeepseekV4IndexerCache` |
| **Compressor State Cache** | float32 (KV+score sliding window) | float32 (AscendCompressorStateCache) | `CompressorStateCache` |
| **Topk Indices Buffer** | int32 (共享跨所有 indexer 层) | int32 | `DeepseekV4Model.topk_indices_buffer` |
| **Hamming Sparse Cache** (kvcomp) | — | hashk_caches | `kvcomp_attn/attention_utils.py` |

---

### 四、vllm → vllm-ascend 关键适配点

1. **KV Cache Coordinator**: `AscendHybridKVCacheCoordinator` 替代默认 coordinator，处理 DSv4 的多组 full attention（C4 + C128）和 SWA (decode时 hit_length=0)
2. **Block Size 限制**: DSv4 只支持 32/64/128（默认32），对应不同 DSA block 配置
3. **KV Cache 分配**: A5 分割为 `(k, dsa_k, dsa_k_scale)`；A3 分割为 `(k, v, dsa_k, dsa_k_scale)`
4. **DSA Position Buffer**: 独立的 CPU buffer 计算 compressed positions
5. **Seq Lens CPU Sync**: DSA 需要 CPU 侧 sequence length 同步（NPU event机制）
6. **ACLgraph Memory Profiling 跳过**: DSv4 DSA compressed attention 不做预分配 profiling
7. **Layer Binding**: 用 `extract_dsv4_layer_index()` 按 compress_ratios 排序绑定 KV cache
8. **核心算子映射**: Triton kernel → Ascend NPU 自定义算子
   - `flash_mla_with_kvcache` → `npu_sparse_attn_sharedkv`
   - Triton indexer → `npu_quant_lightning_indexer`
   - Triton compressor → `torch.ops._C_ascend.compressor`
   - Triton RoPE → `torch_npu.npu_rotary_mul` / `npu_inplace_partial_rotary_mul`
   - Triton scatter → `npu_scatter_nd_update`
   - Triton RMSNorm → `npu_rms_norm_dynamic_quant` / `npu_kv_rmsnorm_rope_cache`

---

### 五、关键代码位置索引

| 组件 | vllm 文件 | vllm-ascend 文件 |
|------|-----------|-----------------|
| Model | `vllm/model_executor/models/deepseek_v4.py` | `vllm_ascend/models/deepseek_v4.py` |
| Attention wrapper | `vllm/model_executor/layers/deepseek_v4_attention.py` | — (集成在 dsa_v1) |
| MLA Attention impl | `vllm/v1/attention/backends/mla/flashmla_sparse.py` | `vllm_ascend/attention/dsa_v1.py` |
| SFA impl | — | `vllm_ascend/attention/sfa_v1.py` |
| MLA impl | `vllm/v1/attention/backends/mla/flashmla.py` | `vllm_ascend/attention/mla_v1.py` |
| SWA backend | `vllm/v1/attention/backends/mla/sparse_swa.py` | — (集成在 dsa_v1) |
| Indexer | `vllm/v1/attention/backends/mla/indexer.py` | — (集成在 sfa_v1/dsa_v1) |
| Compressor | `vllm/model_executor/layers/deepseek_compressor.py` | `vllm_ascend/models/deepseek_v4.py:598` |
| DSA-CP | — | `vllm_ascend/attention/context_parallel/dsa_cp.py` |
| MLA-CP | — | `vllm_ascend/attention/context_parallel/mla_cp.py` |
| KV Cache Coordinator patch | — | `vllm_ascend/patch/platform/patch_kv_cache_coordinator.py` |
| Fused ops (qnorm, rope, quant, insert) | `vllm/v1/attention/ops/deepseek_v4_ops/` | Ascend NPU custom ops |
| Config | `vllm/transformers_utils/configs/deepseek_v4.py` | — (共用上游 config) |
| MTP | `vllm/model_executor/models/deepseek_v4_mtp.py` | `vllm_ascend/models/deepseek_v4_mtp.py` |
| KVComp (Hamming) | — | `vllm_ascend/attention/kvcomp_attn/attention_utils.py` |