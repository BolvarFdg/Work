#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASR 服务性能压测脚本（持续并发模式）

- 从文件夹读取全部音频文件，总请求数超出文件数时自动循环复用
- 按 CONCURRENCIES 数组逐档测试；档内为持续并发：N 个 worker 各自循环取任务，
  一个请求返回后立即发起下一个，任意时刻在途请求数恒等于 N
- 统计端到端耗时（含网络）与服务端耗时（响应 json 的 time 字段）
- 结果打印到控制台，并保存 JSON 文件

依赖: pip install requests
用法: python asr_perf_test.py
"""

import base64
import json
import math
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests

# ==================== 配置区 ====================
AUDIO_DIR = "/data/audio_files"                  # 音频文件夹路径
URL = "http://127.0.0.1:8000/audio/retrieve"     # 服务接口地址
LANGUAGE = "en"                                  # 语项 lang
TOP_K = 10                                       # 检索 top_k
DOMAINS = ["xxxx", "xxx"]                        # 检索域列表
CONCURRENCIES = [1, 4, 8, 16, 32]                # 并发数数组，按顺序逐档测试
TOTAL_REQUESTS = 100                             # 每个并发档位的总请求数
WARMUP_REQUESTS = 3                              # 每档正式测试前的预热请求数（不计入统计）
REQUEST_TIMEOUT = 300                            # 单请求超时（秒）
LEVEL_COOLDOWN = 2.0                             # 两个并发档位之间的冷却时间（秒）
SERVER_TIME_FIELD = "time"                       # 响应 json 中服务端总耗时字段名
ASR_TIME_FIELD = "asr_time"                      # 模型推理耗时字段名（分段）
ENCODER_TIME_FIELD = "encoder_time"              # 编码(encoder)耗时字段名（分段）
SERVER_TIME_IN_MS = True                         # 以上耗时单位为毫秒；若为秒改为 False
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".pcm"}   # 识别的音频后缀
OUTPUT_FILE = "/data/asr_perf_result_{ts}.json"  # 结果保存路径，{ts} 自动替换为时间戳
SAVE_RAW = True                                  # 结果文件中是否保存逐请求明细
# ================================================


def load_audios():
    audio_dir = Path(AUDIO_DIR)
    if not audio_dir.is_dir():
        raise SystemExit(f"音频目录不存在: {AUDIO_DIR}")
    files = sorted(p for p in audio_dir.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS)
    if not files:
        raise SystemExit(f"音频目录下没有匹配 {AUDIO_EXTENSIONS} 的文件: {AUDIO_DIR}")
    return [(f.name, base64.b64encode(f.read_bytes()).decode()) for f in files]


def build_payload(audio_b64: str) -> dict:
    """构造请求体。字段名与服务接口不一致时，只需修改这里。"""
    return {
        "base64_audio": audio_b64,
        "top_k": TOP_K,
        "domain": DOMAINS,
        "lang": LANGUAGE,
    }


def extract_time_ms(resp_json: dict, field: str):
    val = resp_json.get(field)
    if val is None and isinstance(resp_json.get("data"), dict):
        val = resp_json["data"].get(field)
    try:
        val = float(val)
    except (TypeError, ValueError):
        return None
    return val if SERVER_TIME_IN_MS else val * 1000.0


def send_one(session: requests.Session, audio_b64: str) -> dict:
    t0 = time.perf_counter()
    try:
        resp = session.post(URL, json=build_payload(audio_b64), timeout=REQUEST_TIMEOUT)
    except Exception as exc:
        return {
            "ok": False,
            "e2e_ms": round((time.perf_counter() - t0) * 1000, 2),
            "server_ms": None,
            "asr_ms": None,
            "encoder_ms": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    e2e_ms = round((time.perf_counter() - t0) * 1000, 2)
    if resp.status_code != 200:
        return {
            "ok": False,
            "e2e_ms": e2e_ms,
            "server_ms": None,
            "asr_ms": None,
            "encoder_ms": None,
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    try:
        rj = resp.json()
    except ValueError:
        return {
            "ok": False,
            "e2e_ms": e2e_ms,
            "server_ms": None,
            "asr_ms": None,
            "encoder_ms": None,
            "error": "响应不是 JSON",
        }
    server_ms = extract_time_ms(rj, SERVER_TIME_FIELD)
    asr_ms = extract_time_ms(rj, ASR_TIME_FIELD)
    encoder_ms = extract_time_ms(rj, ENCODER_TIME_FIELD)
    code = rj.get("code")
    if code not in (None, 0, 200):
        return {
            "ok": False,
            "e2e_ms": e2e_ms,
            "server_ms": server_ms,
            "asr_ms": asr_ms,
            "encoder_ms": encoder_ms,
            "error": f"业务错误 code={code}: {str(rj)[:200]}",
        }
    return {
        "ok": True,
        "e2e_ms": e2e_ms,
        "server_ms": server_ms,
        "asr_ms": asr_ms,
        "encoder_ms": encoder_ms,
        "error": None,
    }


def percentile(sorted_vals: list, p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def dist_stats(sorted_vals: list) -> dict:
    if not sorted_vals:
        return {}
    return {
        "avg": round(sum(sorted_vals) / len(sorted_vals), 1),
        "p50": round(percentile(sorted_vals, 50), 1),
        "p90": round(percentile(sorted_vals, 90), 1),
        "p95": round(percentile(sorted_vals, 95), 1),
        "p99": round(percentile(sorted_vals, 99), 1),
        "min": round(sorted_vals[0], 1),
        "max": round(sorted_vals[-1], 1),
    }


def do_warmup(audios: list):
    if WARMUP_REQUESTS <= 0:
        return
    print(f"    预热 {WARMUP_REQUESTS} 个请求（不计入统计）...")
    session = requests.Session()
    for i in range(WARMUP_REQUESTS):
        b64 = audios[i % len(audios)][1]
        try:
            session.post(URL, json=build_payload(b64), timeout=REQUEST_TIMEOUT)
        except Exception:
            pass
    session.close()


def run_level(concurrency: int, task_b64s: list) -> tuple:
    """持续并发：concurrency 个 worker 线程各自循环取任务，完成一个立即补下一个。"""
    task_q = queue.Queue()
    for b64 in task_b64s:
        task_q.put(b64)
    total = len(task_b64s)
    results = []
    lock = threading.Lock()
    done_cnt = [0]
    step = max(1, total // 10)

    def worker():
        session = requests.Session()
        while True:
            try:
                b64 = task_q.get_nowait()
            except queue.Empty:
                session.close()
                return
            r = send_one(session, b64)
            with lock:
                results.append(r)
                done_cnt[0] += 1
                done = done_cnt[0]
            if done % step == 0 or done == total:
                print(f"\r    进度: {done}/{total}", end="", flush=True)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for _ in range(concurrency):
            pool.submit(worker)
    wall_s = time.perf_counter() - t0
    print()
    return results, wall_s


def summarize(concurrency: int, results: list, wall_s: float) -> dict:
    ok = [r for r in results if r["ok"]]
    e2e = sorted(r["e2e_ms"] for r in ok)
    srv = sorted(r["server_ms"] for r in ok if r["server_ms"] is not None)
    asr = sorted(r.get("asr_ms") for r in ok if r.get("asr_ms") is not None)
    enc = sorted(r.get("encoder_ms") for r in ok if r.get("encoder_ms") is not None)
    e2e_stats = dist_stats(e2e)
    srv_stats = dist_stats(srv)
    asr_stats = dist_stats(asr)
    enc_stats = dist_stats(enc)
    net_avg = (
        round(e2e_stats["avg"] - srv_stats["avg"], 1)
        if e2e_stats and srv_stats
        else None
    )
    other_avg = (
        round(srv_stats["avg"] - asr_stats["avg"] - enc_stats["avg"], 1)
        if srv_stats and asr_stats and enc_stats
        else None
    )
    errors = [r["error"] for r in results if not r["ok"]][:3]
    return {
        "concurrency": concurrency,
        "total": len(results),
        "success": len(ok),
        "failed": len(results) - len(ok),
        "wall_s": round(wall_s, 3),
        "qps": round(len(ok) / wall_s, 2) if wall_s > 0 else 0.0,
        "e2e_ms": e2e_stats,
        "server_ms": srv_stats,
        "asr_ms": asr_stats,
        "encoder_ms": enc_stats,
        "other_avg_ms": other_avg,
        "network_avg_ms": net_avg,
        "sample_errors": errors,
    }


def print_level_report(s: dict):
    print(f"    请求总数: {s['total']} | 成功: {s['success']} | 失败: {s['failed']}")
    print(f"    墙钟时间: {s['wall_s']}s | 吞吐: {s['qps']} QPS")
    if s["e2e_ms"]:
        e = s["e2e_ms"]
        print(
            f"    端到端耗时(含网络): avg={e['avg']}ms p50={e['p50']}ms "
            f"p90={e['p90']}ms p95={e['p95']}ms max={e['max']}ms"
        )
    if s["server_ms"]:
        v = s["server_ms"]
        print(
            f"    服务端总耗时(time): avg={v['avg']}ms p50={v['p50']}ms "
            f"p90={v['p90']}ms p95={v['p95']}ms"
        )
    else:
        print("    服务端总耗时: 响应中未找到 time 字段（检查 SERVER_TIME_FIELD 配置）")
    if s["asr_ms"]:
        a = s["asr_ms"]
        print(
            f"    decoder time(asr_time): avg={a['avg']}ms p50={a['p50']}ms "
            f"p90={a['p90']}ms p95={a['p95']}ms"
        )
    if s["encoder_ms"]:
        c = s["encoder_ms"]
        print(
            f"    encoder time(encoder_time): avg={c['avg']}ms p50={c['p50']}ms "
            f"p90={c['p90']}ms p95={c['p95']}ms"
        )
    if s["other_avg_ms"] is not None:
        print(f"    其他耗时(总-decoder-encoder, 如检索): avg={s['other_avg_ms']}ms")
    if s["network_avg_ms"] is not None:
        print(f"    网络开销(端到端-服务端): avg={s['network_avg_ms']}ms")
    for err in s["sample_errors"]:
        print(f"    失败示例: {err[:120]}")


def print_final_table(all_levels: list):
    print("\n" + "=" * 60)
    print("各并发档位汇总")
    print("=" * 60)
    for s in all_levels:
        succ_rate = f"{s['success'] / s['total'] * 100:.1f}%" if s["total"] else "-"
        print(f"\n[并发 {s['concurrency']}] 请求: {s['total']} | 成功率: {succ_rate} | "
              f"QPS: {s['qps']} | 墙钟: {s['wall_s']}s")
        if s["e2e_ms"]:
            print(f"  端到端(含网络): avg={s['e2e_ms']['avg']}ms "
                  f"p50={s['e2e_ms']['p50']}ms p95={s['e2e_ms']['p95']}ms")
        if s["server_ms"]:
            print(f"  服务端总耗时(time): avg={s['server_ms']['avg']}ms "
                  f"p50={s['server_ms']['p50']}ms p95={s['server_ms']['p95']}ms")
        if s["asr_ms"]:
            print(f"  decoder time: avg={s['asr_ms']['avg']}ms "
                  f"p50={s['asr_ms']['p50']}ms p95={s['asr_ms']['p95']}ms")
        if s["encoder_ms"]:
            print(f"  encoder time: avg={s['encoder_ms']['avg']}ms "
                  f"p50={s['encoder_ms']['p50']}ms p95={s['encoder_ms']['p95']}ms")
        if s["other_avg_ms"] is not None:
            print(f"  其他耗时(总-decoder-encoder, 如检索): avg={s['other_avg_ms']}ms")
        if s["network_avg_ms"] is not None:
            print(f"  网络开销(端到端-服务端): avg={s['network_avg_ms']}ms")


def main():
    print("=" * 88)
    print("ASR 服务性能压测（持续并发模式）")
    print(f"服务地址: {URL}")
    print(f"音频目录: {AUDIO_DIR}")
    print(f"语言: {LANGUAGE} | 每档请求数: {TOTAL_REQUESTS} | 并发档位: {CONCURRENCIES}")
    print("=" * 88)

    audios = load_audios()
    preview = ", ".join(n for n, _ in audios[:5])
    print(f"已加载音频 {len(audios)} 个: {preview}{' ...' if len(audios) > 5 else ''}")

    all_levels = []
    for conc in CONCURRENCIES:
        print("\n" + "=" * 88)
        print(f"并发档位: {conc}")
        print("=" * 88)
        do_warmup(audios)
        task_b64s = [audios[i % len(audios)][1] for i in range(TOTAL_REQUESTS)]
        results, wall_s = run_level(conc, task_b64s)
        summary = summarize(conc, results, wall_s)
        print_level_report(summary)
        if SAVE_RAW:
            summary["raw"] = results
        all_levels.append(summary)
        if LEVEL_COOLDOWN > 0 and conc != CONCURRENCIES[-1]:
            print(f"    冷却 {LEVEL_COOLDOWN}s ...")
            time.sleep(LEVEL_COOLDOWN)

    print_final_table(
        [{k: v for k, v in s.items() if k != "raw"} for s in all_levels]
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(OUTPUT_FILE.format(ts=ts) if "{ts}" in OUTPUT_FILE else OUTPUT_FILE)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "url": URL,
            "audio_dir": AUDIO_DIR,
            "language": LANGUAGE,
            "concurrencies": CONCURRENCIES,
            "total_requests_per_level": TOTAL_REQUESTS,
            "warmup_requests": WARMUP_REQUESTS,
            "audio_count": len(audios),
        },
        "results": all_levels,
    }
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
