DataLoader 是训练和模型之间的**数据桥梁**。它负责把原始数据变成模型 `forward` 能直接吃的 tensor batch。具体做了以下事情：

### 全景图

```
原始数据（ShareGPT 对话）
  │
  ▼  prepare_data.py 预处理
Arrow 数据集（token_ids + loss_mask + seq_len）
  │
  ▼  ArrowDataset.__getitem__()（DataLoader worker 进程，12个并行）
逐样本处理：
  ① 查本地有没有缓存的 hidden states
     ├─ 有 → 直接加载 .safetensors
     └─ 没有 → HTTP 请求 vLLM 端点，让 Qwen3-8B 跑前向，返回第2/18/33层+最后一层隐状态
  ② 拆分隐状态：3层拼接成 hidden_states，最后一层单独成 verifier_last_hidden_states
  ③ 加 position_ids、lengths
  ④ 加均匀噪声增强（AddUniformNoise，std=0.05）
  │
  ▼  collate_fn（拼批）
多个样本拼接 → pad 到 total_seq_len=8192 → 生成 document_ids
  │
  ▼  返回一个 batch dict，送到 GPU
{"hidden_states": [1, 8192, 3*hidden_size],
 "input_ids": [1, 8192],
 "verifier_last_hidden_states": [1, 8192, hidden_size],
 "loss_mask": [1, 8192],
 "document_ids": [1, 8192],
 "position_ids": [1, 8192]}
  │
  ▼  trainer.py:423-428  搬到 GPU
gpu_batch = {k: v.to(local_rank) for ...}
  │
  ▼  trainer.py:431
self.model(**gpu_batch, ...)   ← 前向传播
```

### 具体代码对应

**① 加载/生成 hidden states** — `data.py:351-398`（`ArrowDataset._get_raw_data`）：

```python
def _get_raw_data(self, index):
    # 先查本地缓存
    candidate_path = self.hidden_states_path / f"hs_{file_idx}.safetensors"
    loaded_hs = _maybe_load_hs_file(candidate_path)          # :353-354

    if loaded_hs is None:                                     # 没缓存
        match self.on_missing:
            case "generate":
                loaded_hs = self._maybe_generate_hs(index)  # :358-359 → 调 vLLM

    # 拆分返回：
    return {
        "hidden_states": loaded_hs["hidden_states"][:, :-1].flatten(1),
            # [seq_len, 3, hidden_size] → [seq_len, 3*hidden_size]  3层拼接
        "input_ids": loaded_hs["token_ids"],                 # [seq_len]
        "verifier_last_hidden_states": loaded_hs["hidden_states"][:, -1],
            # [seq_len, hidden_size]  最后一层单独取出
        "loss_mask": self.data[index]["loss_mask"],          # [seq_len]  哪些是 assistant token
    }
```

**② 调 vLLM 生成** — `data.py:311-349`（`_maybe_generate_hs`）：

```python
def _maybe_generate_hs(self, index):
    if not self.client:
        self._setup_client()    # :289-302  创建 OpenAI client，base_url=vllm_endpoint

    hs_filepath = generate_hidden_states(    # :319-325  HTTP 请求 vLLM
        self.client, self.model, client_item,  # client_item 含 input_ids
        timeout=..., max_retries=...,
    )
    # vLLM 用 Qwen3-8B 跑一遍前向，把第 2/18/33 层 + 最后一层的隐状态存成 safetensors

    match self.on_generate:
        case "delete": Path(hs_filepath).unlink()   # 用完即删（--on-generate delete）
        case "cache": shutil.move(hs_filepath, ...)  # 或缓存到本地
```

**③ 加噪声增强** — `BaseDataset.__getitem__`（`data.py:175-215`）：

```python
def __getitem__(self, index):
    data = self._get_raw_data(index)           # 上面的 ①
    # 转 dtype
    data = {k: v.to(self.hidden_states_dtype) if "hidden_states" in k else v ...}
    # 补 position_ids 和 lengths
    data["position_ids"] = torch.arange(seq_len)
    data["lengths"] = torch.tensor([seq_len])
    # 加噪声 ← noise_transforms.py:23-25
    if self.transform:                          # AddUniformNoise(std=0.05)
        data = self.transform(data)             # data["hidden_states"] += 2*(rand-0.5)*0.05
    return data
```

**④ 拼批（collate_fn）** — `data.py:498-562`：

```python
def collate_fn(batch: list):
    # 多个样本沿 seq 维拼接
    for key in batch[0]:
        collated_data[key] = torch.cat([b[key] for b in batch], dim=0)
        # pad 到 max_len=8192，加 batch 维 → [1, 8192, ...]

    # 生成 document_ids：标记每个位置属于哪个文档，padding 位为 -1
    document_ids = torch.repeat_interleave(
        torch.arange(num_docs), lengths         # :548-556
    )
    # → [1, 8192]，如 [0,0,0,1,1,1,1,-1,-1,...]
    collated_data["document_ids"] = document_ids
    return collated_data
```

### 一句话总结

DataLoader = **把原始对话文本 →（vLLM 生成隐状态）→ 拼批 + pad + 加噪声 → 产出 GPU batch**。其中 vLLM 调用发生在 DataLoader 的 worker 进程里（`__getitem__`），不在模型前向传播里。