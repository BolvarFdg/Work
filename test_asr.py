# asr_encoder.py —— 批量编码 + B 截取（Qwen3-ASR-1.7B, 16k 单声道）
import torch

# ===== 结构常量（与 encoder 配置对应: n_window=50, n_window_infer=800）=====
HOP = 160            # mel hop: 10ms @16k
CHUNK = 100          # n_window*2 = 100 帧(1秒)一个 conv 块
TPC = 13             # 每 conv 块输出 13 个 token
SAMPLE_RATE = 16000
MIN_B_SECONDS = 0.3  # B 短于此值不截取, 整段送检索
# A 时长为 8 秒整数倍(n_window_infer=800帧)时, B 截取与单独编码 B 完全等价


def tokens_from_frames(frames: int) -> int:
    """mel 帧数 → token 数（与引擎 _get_feat_extract_output_lengths 完全一致）"""
    full, leave = divmod(frames, CHUNK)
    feat = (leave - 1) // 2 + 1
    tail = ((feat - 1) // 2 + 1 - 1) // 2 + 1
    return full * TPC + tail


def tokens_from_samples(n_samples: int) -> int:
    """采样点数 → token 数（torch.stft center=True: 帧数 = N//hop + 1）"""
    return tokens_from_frames(n_samples // HOP + 1)


def encode_batch(speech_model, feature_extractor, audio_list, time_b_list, device):
    """
    入参:
      speech_model      : Qwen3ASRThinkerForConditionalGeneration（官方 qwen-asr）
      feature_extractor : processor.feature_extractor（WhisperFeatureExtractor）
      audio_list        : List[ndarray] 每条为 A+B 拼接后的整段波形（16k 单通道）
      time_b_list       : List[float|None] 每条 B 部分时长(秒)；无前缀传 None
    返回 dict:
      model_embeds     : List[Tensor(T_i, 2048)]  完整 A+B embeds，逐请求透传给 vLLM
      retrieval_embeds : Tensor(B, T_max', 2048)  B 截取后 pad 0 的 3D，送检索
      retrieval_lens   : List[int]                每条有效 token 数（池化只取前 lens 帧）
      retrieval_pieces : List[Tensor]             B 截取原始变长列表（备用）
    """
    assert len(audio_list) == len(time_b_list)

    # ① 批量提 mel —— 用真实 attention_mask（改动点A2）
    audio_inputs = feature_extractor(
        audio_list, sampling_rate=SAMPLE_RATE, padding="longest",
        return_tensors="pt", return_attention_mask=True,
    )
    input_features = audio_inputs["input_features"].to(device)
    feature_attention_mask = audio_inputs["attention_mask"].to(device)   # 真实 mask!

    # ② 整批编码 —— 内部按 mask 真长度逐条切、逐条编码，padding 不进 tower
    #    （前提：get_audio_features 内 stack 已改回 cat，返回扁平 (ΣT_i, 2048)）
    flat = speech_model.get_audio_features(input_features, feature_attention_mask)
    if flat.ndim == 3:                                   # 兼容单条调用多出的维度
        flat = flat.reshape(-1, flat.shape[-1])

    # ③ 按各条长度拆开 —— 干净的完整 embeds，无 padding 无 NaN
    frames_list = [int(x) for x in feature_attention_mask.sum(-1).tolist()]
    t_list = [tokens_from_frames(f) for f in frames_list]
    assert flat.shape[0] == sum(t_list), \
        f"扁平长度 {flat.shape[0]} != 各段 token 之和 {sum(t_list)}，布局异常"
    model_embeds = list(torch.split(flat, t_list, dim=0))     # List[(T_i, 2048)]

    # ④ 逐条 B 尾部截取（三层守卫）→ 检索用
    retrieval_pieces = []
    for i, emb in enumerate(model_embeds):
        n_total = len(audio_list[i])                          # 整段采样数
        t_b_sec = time_b_list[i]
        n_b = round(t_b_sec * SAMPLE_RATE) if t_b_sec is not None else n_total
        piece = emb                                           # 默认整段
        if MIN_B_SECONDS * SAMPLE_RATE <= n_b < n_total:      # 守卫1/2: 最短时长 & B<整段
            t_b = tokens_from_samples(n_b)
            if 0 < t_b <= emb.shape[0]:                       # 守卫3: 数值一致
                piece = emb[-t_b:]
        retrieval_pieces.append(piece)

    # ⑤ 检索 3D 组装：pad 0（不是 NaN！），有效长度单独返回
    t_max = max(p.shape[0] for p in retrieval_pieces)
    retrieval_embeds = torch.zeros(
        len(retrieval_pieces), t_max, retrieval_pieces[0].shape[-1],
        dtype=retrieval_pieces[0].dtype, device=retrieval_pieces[0].device)
    retrieval_lens = []
    for i, p in enumerate(retrieval_pieces):
        retrieval_embeds[i, : p.shape[0]] = p
        retrieval_lens.append(p.shape[0])

    return {
        "model_embeds": model_embeds,          # → 模型推理（逐请求）
        "retrieval_embeds": retrieval_embeds,  # → 检索（3D batch）
        "retrieval_lens": retrieval_lens,
        "retrieval_pieces": retrieval_pieces,
    }


def retrieval_query(retrieval_embeds, retrieval_lens):
    """检索查询向量：每条只在有效长度内均值池化 → (B, 2048)"""
    return torch.stack([
        retrieval_embeds[i, : retrieval_lens[i]].mean(dim=0)
        for i in range(retrieval_embeds.shape[0])
    ])


# ===== 调用示例 =====
# result = encode_batch(speech_model, feature_extractor, audio_list, time_b_list, device)
#
# 检索：query = retrieval_query(result["retrieval_embeds"], result["retrieval_lens"])
#       keywords_list = retriever.search_batch(query)
#
# 模型（逐请求，embeds 是该请求的完整 A+B）：
# for i, req in enumerate(requests):
#     inputs = {"prompt": build_prompt(keywords_list[i], str_A_list[i]),
#               "multi_modal_data": {"audio": result["model_embeds"][i]}}
#     ...  # engine.generate