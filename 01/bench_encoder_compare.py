#!/usr/bin/env python
"""对比 Qwen3-Omni audio tower 两种运行方式的单条编码延迟:

  A) transformers 直接加载塔 (干预服务现状) —— 进程内 forward 计时
  B) vllm-ascend encoder-only 实例 (EC producer) —— HTTP primer 全链路计时

在 NPU (910B) 机器上、你的 vllm/vllm-ascend/transformers 环境里运行:

  python bench_encoder_compare.py \
      --model /path/to/Qwen3-Omni \
      --audio test.wav \
      --npu 0 \
      --rounds 50

注意:
  * 请在 omni 服务停掉或指定空闲卡的机器上跑 (脚本会占用一张卡, 默认卡 0)。
  * vllm 侧计的是 HTTP 全链路 (含 mel 特征提取 + 调度 + 塔 + EC 落盘),
    transformers 侧的塔计时不含 mel —— 对 vllm 更严格, 若 vllm 仍更快, 结论更硬。
  * 每一轮使用内容互不相同的音频变体, 避免 EC/处理器缓存命中造成假延迟;
    最后一并做两边输出的逐 token 余弦相似度校验 (数值一致性)。
  * 意义: A vs B 就是你迁移决策要付的"编码路径差价"。
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import requests
import torch

try:
    import torch_npu  # noqa: F401  # 注册 npu 后端
except ImportError:
    print("需要 torch_npu (请在 910B 机器的 NPU 环境运行)")
    raise


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def load_audio_16k(path: str) -> np.ndarray:
    """加载任意格式音频 -> 16kHz mono float32 numpy."""
    try:
        import torchaudio
        wav, sr = torchaudio.load(path)
        wav = wav.mean(dim=0)
        if sr != 16000:
            wav = torchaudio.functional.resample(wav, sr, 16000)
        return wav.numpy().astype(np.float32)
    except Exception:
        import soundfile as sf
        wav, sr = sf.read(path, dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        if sr != 16000:
            raise RuntimeError(f"soundfile 无法重采样: 源采样率 {sr} != 16000, 请安装 torchaudio")
        return wav


def save_wav(path: str, audio: np.ndarray, sr: int = 16000):
    try:
        import soundfile as sf
        sf.write(path, audio, sr)
    except Exception:
        import torchaudio
        torchaudio.save(path, torch.from_numpy(audio).unsqueeze(0), sr)


def make_variant(audio: np.ndarray, seed: int) -> np.ndarray:
    """生成内容不同但声学几乎不变的变体: 末尾追加随机长度(1-4096样本)的近静音。

    必须改内容: EC 缓存与 processor 缓存都按内容 hash 寻址,
    相同内容第二轮起会命中缓存、跳过塔计算, 测出来的是假延迟。
    """
    rng = np.random.default_rng(seed)
    tail = (rng.standard_normal(rng.integers(1, 4096)) * 1e-5).astype(np.float32)
    return np.concatenate([audio, tail])


def stats_ms(samples_ms):
    a = np.array(samples_ms)
    return {
        "mean": a.mean(),
        "p50": np.percentile(a, 50),
        "p99": np.percentile(a, 99),
    }


def report(name: str, s):
    print(f"  {name:<28s} mean {s['mean']:7.2f} ms | "
          f"p50 {s['p50']:7.2f} ms | p99 {s['p99']:7.2f} ms")


# ---------------------------------------------------------------------------
# A) transformers 塔 (干预服务现状)
# ---------------------------------------------------------------------------

def load_tower_only(model_dir: str, npu_dev: int, attn_impl: str):
    """只加载 audio tower 权重 (checkpoint 里 audio_tower.* 前缀), 不加载 30B LM。"""
    from transformers import AutoConfig
    from transformers.models.qwen3_omni_moe.modeling_qwen3_omni_moe import (
        Qwen3OmniMoeAudioEncoder,
    )

    cfg = AutoConfig.from_pretrained(model_dir)
    audio_cfg = getattr(cfg, "audio_config", None)
    if audio_cfg is None:
        audio_cfg = cfg.thinker_config.audio_config
    audio_cfg._attn_implementation = attn_impl

    tower = Qwen3OmniMoeAudioEncoder(audio_cfg).to(torch.bfloat16)

    index_path = Path(model_dir) / "model.safetensors.index.json"
    with open(index_path) as f:
        index = json.load(f)
    weight_map = index["weight_map"]
    tower_keys = {k: v for k, v in weight_map.items() if "audio_tower." in k}
    assert tower_keys, "checkpoint 里没找到 audio_tower.* 权重"

    shards = sorted(set(tower_keys.values()))
    state = {}
    for shard in shards:
        from safetensors.torch import load_file
        for k, v in load_file(Path(model_dir) / shard).items():
            if "audio_tower." in k:
                state[k.split("audio_tower.")[-1]] = v
    missing, unexpected = tower.load_state_dict(state, strict=False)
    # positional_embedding 是非持久 buffer (构造时计算), 缺失是正常的
    real_missing = [m for m in missing if "positional_embedding" not in m]
    assert not real_missing, f"塔权重缺失: {real_missing[:5]}"
    assert not unexpected, f"多余权重: {unexpected[:5]}"

    tower.npu(npu_dev)
    tower.eval()
    n_params = sum(p.numel() for p in tower.parameters())
    print(f"[transformers] 塔加载完成: {n_params/1e6:.0f}M 参数, "
          f"{n_params*2/1e9:.2f} GB bf16, attn={attn_impl}")
    return tower


def get_tower_inputs(feats):
    """把 feature_extractor 的输出转成塔的输入契约。

    塔期望 (照抄 thinker forward 的变换):
      input_features: (mel_bins, total_valid_frames) 二维, 无 batch 维, 无 padding
      feature_lens:   (num_audios,) 每条音频的真实帧数

    FE 实际返回的是 padding 过的 [B, mel, T] (T 凑到 100 帧整数倍) 外加:
      - "feature_lens": 真实帧数 (帧单位, 权威值) —— 优先用
      - "attention_mask": 可能是帧级 [B,T] 或样本级 [B,样本数] (如 [1,480000])
    本脚本 batch=1, 统一走"按真实长度裁尾部 padding"路线, 简单且对三种 FE 输出都对。
    """
    mel = feats["input_features"]
    if isinstance(mel, (list, tuple)):
        mel = mel[0]
    if mel.dim() == 2:
        mel = mel.unsqueeze(0)  # [B, mel_bins, T_padded]

    if "feature_lens" in feats:
        flens = torch.as_tensor(feats["feature_lens"]).reshape(-1).long()
    else:
        mask = None
        for key in ("feature_attention_mask", "attention_mask"):
            if key in feats:
                m = feats[key]
                if isinstance(m, (list, tuple)):
                    m = m[0]
                mask = torch.as_tensor(m)
                break
        if mask is None:
            flens = torch.tensor([mel.shape[-1]], dtype=torch.long)
        elif mask.shape[-1] == mel.shape[-1]:  # 帧级 mask
            flens = mask.sum(-1).long()
        else:  # 样本级 mask (样本数), 换算成帧
            hop = mask.shape[-1] / mel.shape[-1]
            flens = torch.round(mask.float().sum(-1) / hop).long()
            flens = flens.clamp(max=mel.shape[-1])

    t_valid = int(flens.sum())
    assert 0 < t_valid <= mel.shape[-1], \
        f"有效帧数 {t_valid} 越界 (mel T={mel.shape[-1]})"
    if t_valid < mel.shape[-1]:
        print(f"  mel 裁剪 padding: {mel.shape[-1]} -> {t_valid} 帧")
    inp = mel[0][:, :t_valid]  # [mel_bins, t_valid]
    return inp, torch.tensor([t_valid], dtype=torch.long)


def run_transformers(tower, audio: np.ndarray, model_dir: str,
                     rounds: int, warmup: int):
    from transformers import AutoProcessor

    proc = AutoProcessor.from_pretrained(model_dir)

    # mel 特征提取 (CPU), 单独计时
    t0 = time.perf_counter()
    feats = proc.feature_extractor([audio], sampling_rate=16000,
                                    return_tensors="pt")
    mel_time_ms = (time.perf_counter() - t0) * 1000

    mel, flens = get_tower_inputs(feats)
    print(f"[transformers] mel: 塔输入 shape={tuple(mel.shape)} "
          f"(mel_bins, 有效帧), frames={int(flens[0])}, "
          f"提取耗时 {mel_time_ms:.2f} ms (CPU, 每条一次)")

    dev = tower.conv2d1.weight.device
    mel_npu = mel.to(dev)
    flens_npu = flens.to(dev).long()

    with torch.inference_mode():
        for _ in range(warmup):
            tower(input_features=mel_npu, feature_lens=flens_npu)
        torch.npu.synchronize()

        times = []
        for _ in range(rounds):
            torch.npu.synchronize()
            t0 = time.perf_counter()
            out = tower(input_features=mel_npu, feature_lens=flens_npu)
            torch.npu.synchronize()
            times.append((time.perf_counter() - t0) * 1000)

    print(f"[transformers] 塔 forward × {rounds} 轮:")
    report("tower forward", stats_ms(times))
    return out.last_hidden_state.float().cpu(), stats_ms(times), mel_time_ms


# ---------------------------------------------------------------------------
# B) vllm encoder-only 实例 (EC producer) 走 HTTP primer
# ---------------------------------------------------------------------------

def wait_healthy(port: int, timeout_s: int, proc: subprocess.Popen, log_path: str):
    t0 = time.time()
    url = f"http://127.0.0.1:{port}/health"
    while time.time() - t0 < timeout_s:
        if proc.poll() is not None:
            raise RuntimeError(
                f"vllm serve 进程退出 (code={proc.returncode})\n日志: {log_path}")
        try:
            if requests.get(url, timeout=3).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError(f"等待 vllm serve 启动超时 ({timeout_s}s), 日志: {log_path}")


def primer_request(session, port, model_dir, wav_path, uuid):
    payload = {
        "model": model_dir,
        "stream": False,
        "messages": [{"role": "user", "content": [
            {"type": "audio_url",
             "audio_url": {"url": f"file://{wav_path}"},
             "uuid": uuid},
            {"type": "text", "text": "hi"},
        ]}],
    }
    r = session.post(f"http://127.0.0.1:{port}/v1/chat/completions",
                     json=payload, timeout=120)
    r.raise_for_status()
    return r.json()


def extract_audio_mm_hash(resp_json):
    ec = resp_json.get("ec_transfer_params") or {}
    # 响应结构: {item_index: {"modality": "audio", "mm_hash": ..., "metadata": {...}}}
    for v in ec.values():
        if isinstance(v, dict) and v.get("modality") == "audio":
            return v["mm_hash"]
    raise RuntimeError(f"响应里没有 audio 的 ec_transfer_params: {resp_json.keys()}")


def run_vllm(model_dir, audio, rounds, warmup, port, npu_dev, gpu_util,
             tmp_root, tower):
    from safetensors.torch import load_file as st_load

    media_dir = tmp_root / "media"
    ec_dir = tmp_root / "ec_cache"
    media_dir.mkdir(parents=True, exist_ok=True)
    server_log = tmp_root / "vllm_server.log"

    # 每轮一个内容不同的变体 (避免缓存命中)
    variants = []
    for i in range(rounds + warmup + 1):
        wav = media_dir / f"var_{i:04d}.wav"
        save_wav(str(wav), make_variant(audio, seed=i))
        uuid = hashlib.sha256(wav.read_bytes()).hexdigest()
        variants.append((str(wav), uuid))
    parity_wav, parity_uuid = variants[-1]

    ec_config = json.dumps({
        "ec_connector": "ECExampleConnector",
        "ec_role": "ec_producer",
        "ec_connector_extra_config": {"shared_storage_path": str(ec_dir)},
    })

    vllm_bin = shutil.which("vllm")
    cmd = [vllm_bin or sys.executable] + ([] if vllm_bin else
           ["-c", "from vllm.entrypoints.cli.main import main; main()"]) + [
        "serve", model_dir,
        "--port", str(port),
        "--mm-encoder-only",
        "--enforce-eager",
        "--disable-prefix-caching",
        "--max-num-batched-tokens", "114688",
        "--gpu-memory-utilization", str(gpu_util),
        "--dtype", "bfloat16",
        "--allowed-local-media-path", str(media_dir),
        "--ec-transfer-config", ec_config,
    ]
    env = dict(os.environ, ASCEND_RT_VISIBLE_DEVICES=str(npu_dev),
               VLLM_LOGGING_LEVEL="INFO")
    print(f"[vllm] 启动 encoder-only 实例: {' '.join(cmd[:4])} ... (日志: {server_log})")
    log_f = open(server_log, "w")
    proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, env=env)
    session = requests.Session()  # 连接池/keep-alive

    try:
        wait_healthy(port, timeout_s=1200, proc=proc, log_path=str(server_log))
        print(f"[vllm] 服务就绪 (端口 {port})")

        # warmup (首轮含引擎首次执行的开销)
        for wav, uuid in variants[:warmup]:
            primer_request(session, port, model_dir, wav, uuid)

        times = []
        for wav, uuid in variants[warmup:rounds + warmup]:
            t0 = time.perf_counter()
            resp = primer_request(session, port, model_dir, wav, uuid)
            times.append((time.perf_counter() - t0) * 1000)

        print(f"[vllm] HTTP primer 全链路 × {rounds} 轮 "
              f"(含 mel + 调度 + 塔 + EC 落盘 + HTTP 往返):")
        report("primer roundtrip", stats_ms(times))

        # ---- 数值一致性: 同一段音频, 两边输出逐 token 余弦 ----
        resp = primer_request(session, port, model_dir, parity_wav, parity_uuid)
        mm_hash = extract_audio_mm_hash(resp)
        ec_file = Path(ec_dir) / mm_hash / "encoder_cache.safetensors"
        for _ in range(50):  # 等落盘 (正常应在响应前已完成)
            if ec_file.exists():
                break
            time.sleep(0.1)
        ec_out = st_load(str(ec_file))["ec_cache"].float()

        # transformers 侧对同一个变体文件重跑一次 (同源解码, 保证可比)
        from transformers import AutoProcessor
        proc_fe = AutoProcessor.from_pretrained(model_dir).feature_extractor
        feats = proc_fe([load_audio_16k(parity_wav)], sampling_rate=16000,
                        return_tensors="pt")
        mel, flens = get_tower_inputs(feats)
        dev = tower.conv2d1.weight.device
        with torch.inference_mode():
            tf_out = tower(input_features=mel.to(dev),
                           feature_lens=flens.to(dev).long())
        tf_out = tf_out.last_hidden_state.float().cpu()

        n_tf, n_ec = tf_out.shape[0], ec_out.shape[0]
        if n_tf == n_ec:
            cos = torch.nn.functional.cosine_similarity(
                tf_out.float().cpu(), ec_out, dim=-1)
            print(f"[parity] token 数一致: {n_tf}; "
                  f"逐 token 余弦 mean {cos.mean():.4f} / min {cos.min():.4f}")
        else:
            print(f"[parity] ⚠ token 数不一致: transformers {n_tf} vs EC {n_ec}, "
                  "请检查 mel 参数是否同源")

        return stats_ms(times)
    finally:
        session.close()
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_f.close()
        print(f"[vllm] 实例已停止")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="Qwen3-Omni 模型目录")
    ap.add_argument("--audio", required=True, help="测试音频文件 (wav/mp3/...)")
    ap.add_argument("--npu", type=int, default=0, help="NPU 卡号 (默认 0)")
    ap.add_argument("--rounds", type=int, default=50, help="计时轮数")
    ap.add_argument("--warmup", type=int, default=5, help="预热轮数")
    ap.add_argument("--port", type=int, default=19534, help="vllm 实例端口")
    ap.add_argument("--gpu-util", type=float, default=0.3,
                    help="encoder 实例的 gpu-memory-utilization")
    ap.add_argument("--tf-attn", choices=["sdpa", "eager"], default="sdpa",
                    help="transformers 侧注意力实现 (默认 sdpa, 与线上干预服务对齐)")
    args = ap.parse_args()

    torch.npu.set_device(args.npu)
    audio = load_audio_16k(args.audio)
    print(f"音频: {args.audio}, {len(audio)/16000:.1f}s @16kHz")

    tmp_root = Path(tempfile.mkdtemp(prefix="enc_bench_"))
    print(f"工作目录: {tmp_root}")
    try:
        # A) transformers 塔直跑
        tower = load_tower_only(args.model, args.npu, args.tf_attn)
        tf_out, tf_stats, mel_ms = run_transformers(
            tower, audio, args.model, args.rounds, args.warmup)

        # B) vllm encoder-only 实例
        vllm_stats = run_vllm(
            args.model, audio, args.rounds, args.warmup, args.port,
            args.npu, args.gpu_util, tmp_root, tower)

        # ---- 汇总 ----
        print("\n" + "=" * 62)
        print("结果汇总 (越小越好)")
        print("-" * 62)
        report("A transformers 塔 forward", tf_stats)
        print(f"  (另计: mel 特征提取 {mel_ms:.2f} ms/条, CPU)")
        report("B vllm primer 全链路", vllm_stats)
        print("-" * 62)
        print("解读:")
        print("  * B 含 mel+HTTP 开销, A 不含 —— B 若仍 ≤ A, 迁移结论成立且更硬")
        print("  * 差值即每条音频可省的 TTFT; 乘以 QPS 得吞吐收益")
        print("  * B 中 vllm 内部真正的塔时间 < B, 想细分可看 server 日志")
        print("=" * 62)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
