#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vLLM Qwen3-Omni 音频转写并发压测脚本
用法: 修改下方配置块后直接运行  python vllm_audio_bench.py
依赖: pip install requests
"""

import csv
import os
import queue
import statistics
import threading
import time

try:
    import requests
except ImportError:
    raise SystemExit("缺少 requests 库, 请先执行: pip install requests")

# ===================== 配置区(按需修改) =====================
BASE_URL = "http://127.0.0.1:8000/v1/chat/completions"   # vllm serve 服务地址 ip:port
MODEL = ""                          # 模型名, 留空则不传, 使用服务端默认模型
AUDIO_DIR = "/data/xxx"             # Linux 服务端上音频文件夹的绝对路径
AUDIO_EXT = ".wav"                  # 音频文件后缀
AUDIO_START = 0                     # 音频文件起始编号(0 或 1)
AUDIO_COUNT = 30                    # 文件夹内音频总数(纯数字命名: 0/1.wav, 1/2.wav ...)
CONCURRENCY = 10                    # 并发数(全程持续压满该并发)
TOTAL_REQUESTS = max(CONCURRENCY * 10, 60)  # 总请求数 = max(并发数*10, 60)
MAX_TOKENS = 256                    # 最大生成 token 数
TEMPERATURE = 0                     # 采样温度
PROMPT_TEXT = "Transcribe the audio into text."
TIMEOUT = 300                       # 单请求超时(秒)
OUTPUT_CSV = "bench_results.csv"    # 每个请求的明细输出文件(与本脚本同目录)
# ============================================================

AUDIO_FILES = [
    f"file://{AUDIO_DIR.rstrip('/')}/{AUDIO_START + i}{AUDIO_EXT}"
    for i in range(AUDIO_COUNT)
]

task_queue = queue.Queue()
for i in range(TOTAL_REQUESTS):
    task_queue.put(i)

results = []
results_lock = threading.Lock()
done_count = 0


def build_payload(audio_url):
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "audio_url", "audio_url": {"url": audio_url}},
                    {"type": "text", "text": PROMPT_TEXT},
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }
    if MODEL:
        payload["model"] = MODEL
    return payload


def worker():
    global done_count
    session = requests.Session()
    while True:
        try:
            idx = task_queue.get_nowait()
        except queue.Empty:
            return
        audio_url = AUDIO_FILES[idx % len(AUDIO_FILES)]
        payload = build_payload(audio_url)
        t0 = time.perf_counter()
        ok, ptok, ctok, err = False, 0, 0, ""
        try:
            resp = session.post(BASE_URL, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                usage = (resp.json().get("usage") or {})
                ptok = usage.get("prompt_tokens", 0) or 0
                ctok = usage.get("completion_tokens", 0) or 0
                ok = True
            else:
                err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - t0

        with results_lock:
            results.append(
                {
                    "request_id": idx + 1,
                    "audio": audio_url,
                    "success": ok,
                    "latency_s": round(latency, 3),
                    "prompt_tokens": ptok,
                    "completion_tokens": ctok,
                    "output_tps": round(ctok / latency, 2) if ok and latency > 0 else 0,
                    "error": err,
                }
            )
            done_count += 1
            n = done_count
        if n % 10 == 0 or n == TOTAL_REQUESTS:
            print(f"[progress] {n}/{TOTAL_REQUESTS}")


def percentile(sorted_data, p):
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return sorted_data[0]
    pos = (len(sorted_data) - 1) * p / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(sorted_data) - 1)
    frac = pos - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def main():
    print("=" * 60)
    print(f"目标地址      : {BASE_URL}")
    print(f"音频目录      : {AUDIO_DIR} (共 {AUDIO_COUNT} 个, 起始编号 {AUDIO_START})")
    print(f"并发数        : {CONCURRENCY}")
    print(f"总请求数      : {TOTAL_REQUESTS}")
    print("=" * 60)

    threads = [threading.Thread(target=worker) for _ in range(CONCURRENCY)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - start

    ok_results = [r for r in results if r["success"]]
    fail_results = [r for r in results if not r["success"]]
    latencies = sorted(r["latency_s"] for r in ok_results)
    total_ctok = sum(r["completion_tokens"] for r in ok_results)
    total_ptok = sum(r["prompt_tokens"] for r in ok_results)

    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_CSV)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print()
    print("=" * 60)
    print(f"总耗时        : {wall:.2f} s")
    print(f"成功/失败     : {len(ok_results)} / {len(fail_results)}")
    if latencies:
        print(f"请求时延(s)   : avg={statistics.mean(latencies):.2f}  "
              f"p50={percentile(latencies, 50):.2f}  p95={percentile(latencies, 95):.2f}  "
              f"p99={percentile(latencies, 99):.2f}  max={max(latencies):.2f}")
        print(f"吞吐量(RPS)   : {len(ok_results) / wall:.2f} req/s")
        print(f"总输出 tokens : {total_ctok} (输入 tokens: {total_ptok})")
        print(f"服务端整体输出: {total_ctok / wall:.2f} tokens/s")
        per_req_tps = [r["output_tps"] for r in ok_results]
        print(f"单请求输出速度: avg={statistics.mean(per_req_tps):.2f}  "
              f"min={min(per_req_tps):.2f}  max={max(per_req_tps):.2f} tokens/s")
    if fail_results:
        print(f"\n失败示例(前3条):")
        for r in fail_results[:3]:
            print(f"  #{r['request_id']} {r['audio']} -> {r['error']}")
    print(f"明细已写入    : {csv_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
