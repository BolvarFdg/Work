#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 推理服务性能测试脚本（零依赖，仅 Python 标准库）

测试指定并发数下的 TTFT / ITL / 端到端延迟 / 吞吐量。

用法示例:
    # 测试 qwen3.8-27B（默认并发 1 5 10 20 30，每档 100 个请求）
    python3 llm_bench.py --url http://localhost:8000 --model qwen3.8-27B --csv result.csv

    # 测试 deepseek-v4-flash，结果追加到同一个 csv 方便对比
    python3 llm_bench.py --url http://localhost:8000 --model deepseek-v4-flash --csv result.csv

    # 自定义并发档位和总请求数
    python3 llm_bench.py --url http://localhost:8000 --model qwen3.8-27B \
        --concurrency 1 5 10 20 30 --total-requests 200
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 固定 prompt 池：两个模型循环使用完全相同的输入，保证测试公平、可复现。
# 刻意混合了短问答 / 数学推理 / 代码 / 翻译 / 长文本摘要 / 英文等任务，
# 同时包含长短不同的输入（影响 prefill 和 TTFT）。
# ---------------------------------------------------------------------------
DEFAULT_PROMPTS = [
    "用一句话解释什么是量子计算。",
    "写一首关于春天的四行短诗。",
    "列举5种常见的设计模式，并用一句话说明各自的用途。",
    "一个班级有30名学生，其中18人喜欢数学，15人喜欢物理，8人两者都喜欢。"
    "请问有多少学生两者都不喜欢？请给出推理过程。",
    "用Python写一个函数，判断给定字符串是否是回文，并附带简单的测试用例。",
    "写一封简短的商务邮件，告知客户项目需要延期一周，语气要诚恳并给出新的交付时间。",
    "请把下面这段话翻译成英文：人工智能正在深刻改变软件开发的方式。大语言模型"
    "可以辅助编写代码、审查缺陷和生成测试，但工程师仍然需要对最终质量负责。",
    "请将下面这段文字总结为3个要点：\n"
    "近年来，随着大语言模型规模的迅速增长，推理成本成为落地应用的核心瓶颈。"
    "业内出现了多种优化方向：一是模型压缩技术，包括量化、剪枝和知识蒸馏；"
    "二是更高效的注意力实现，如FlashAttention和稀疏注意力；"
    "三是推测解码，用小模型起草、大模型验证，从而减少大模型的串行解码步数。"
    "此外，批处理调度与连续批处理也显著提升了服务吞吐量。"
    "实践表明，多种技术组合使用才能在精度与成本之间取得平衡。",
    "Summarize the main causes of World War I in about 80 words.",
    "解释Transformer架构中自注意力机制的作用，以及它为什么比RNN更适合并行计算。",
]


@dataclass
class ReqResult:
    ok: bool = False
    error: str = ""
    ttft_s: float | None = None  # 首 token 延迟（秒）
    e2e_s: float | None = None   # 端到端延迟（秒）
    output_tokens: int = 0
    itls: list = field(default_factory=list)  # token 间隔（秒）


def pct(vals: list, p: float) -> float:
    """线性插值百分位，单位与输入一致"""
    if not vals:
        return float("nan")
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def fmt_ms(vals: list) -> str:
    return (
        f"mean={_mean(vals):8.1f}  "
        f"p50={pct(vals, 50):8.1f}  p90={pct(vals, 90):8.1f}  "
        f"p95={pct(vals, 95):8.1f}  p99={pct(vals, 99):8.1f}"
    )


def _mean(vals: list) -> float:
    return sum(vals) / len(vals) if vals else float("nan")


def make_conn(url: str, timeout: float):
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=timeout)
    return HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)


def build_payload(args, prompt: str, max_tokens: int, stream: bool) -> dict:
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": args.temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    if not args.thinking:
        # Qwen3 系列模板使用 enable_thinking，DeepSeek 系列使用 thinking；
        # vLLM 会自动过滤当前模型模板不支持的变量，两个都传是安全的。
        payload["chat_template_kwargs"] = {"enable_thinking": False, "thinking": False}
    return payload


def check_model_exists(args) -> None:
    """启动后先校验模型名，避免白白跑一轮"""
    try:
        conn = make_conn(args.url, timeout=10)
        conn.request("GET", "/v1/models")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        ids = [m.get("id") for m in data.get("data", [])]
        if args.model in ids:
            print(f"[check] 模型 '{args.model}' 已在服务端加载 ✓")
        else:
            print(f"[check] 警告: 模型 '{args.model}' 不在服务列表中 {ids}，"
                  f"请求可能返回 404，请核对 /v1/models 返回的 id")
    except Exception as e:
        print(f"[check] 无法连接 {args.url} 查询模型列表: {e!r}")


def send_one(args, prompt: str) -> ReqResult:
    """发送单个流式请求，解析 SSE，记录 TTFT / ITL / 输出 token 数"""
    result = ReqResult()
    payload = build_payload(args, prompt, args.max_tokens, stream=True)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    start = time.perf_counter()
    ttft = None
    prev = None
    usage_tokens = None
    content_chunks = 0
    conn = None
    try:
        conn = make_conn(args.url, timeout=args.timeout)
        conn.request("POST", "/v1/chat/completions", body=body, headers=headers)
        resp = conn.getresponse()
        if resp.status != 200:
            err = resp.read(500).decode("utf-8", "replace")
            result.error = f"HTTP {resp.status}: {err[:200]}"
            return result

        buf = b""
        done = False
        while not done:
            chunk = resp.read1(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    done = True
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = obj.get("usage")
                if usage and usage.get("completion_tokens") is not None:
                    usage_tokens = usage["completion_tokens"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    content_chunks += 1
                    now = time.perf_counter()
                    if ttft is None:
                        ttft = now - start
                        prev = now
                    else:
                        result.itls.append(now - prev)
                        prev = now

        result.ttft_s = ttft
        result.e2e_s = time.perf_counter() - start
        result.output_tokens = usage_tokens if usage_tokens is not None else content_chunks
        if result.output_tokens == 0 or ttft is None:
            result.error = "未收到任何输出 token"
        else:
            result.ok = True
        return result
    except Exception as e:
        result.e2e_s = time.perf_counter() - start
        result.error = repr(e)
        return result
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def warmup(args) -> None:
    """每档并发前发送少量小请求预热（不计入统计）"""
    for i in range(args.warmup):
        payload = build_payload(args, DEFAULT_PROMPTS[i % len(DEFAULT_PROMPTS)],
                                max_tokens=4, stream=False)
        try:
            conn = make_conn(args.url, timeout=args.timeout)
            conn.request("POST", "/v1/chat/completions",
                         body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status != 200:
                print(f"[warmup] 第 {i + 1} 个预热请求返回 HTTP {resp.status}")
        except Exception as e:
            print(f"[warmup] 预热请求失败: {e!r}")


def run_level(args, prompts: list, level: int) -> dict:
    print(f"\n{'=' * 60}")
    print(f"并发数 = {level}，总请求数 = {args.total_requests}")
    print("=" * 60)

    if args.warmup > 0:
        print(f"预热中（{args.warmup} 个请求）...")
        warmup(args)

    results: list[ReqResult] = []
    lock = threading.Lock()
    done = 0

    with ThreadPoolExecutor(max_workers=level) as pool:
        futures = [pool.submit(send_one, args, prompts[i % len(prompts)])
                   for i in range(args.total_requests)]
        start = time.perf_counter()
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            with lock:
                done += 1
                if done % 10 == 0 or done == args.total_requests:
                    print(f"  进度 {done}/{args.total_requests}", flush=True)
        wall = time.perf_counter() - start

    ok = [r for r in results if r.ok]
    failed = len(results) - len(ok)
    ttfts_ms = [r.ttft_s * 1000 for r in ok]
    e2es_ms = [r.e2e_s * 1000 for r in ok]
    itls_ms = [x * 1000 for r in ok for x in r.itls]
    out_total = sum(r.output_tokens for r in ok)

    stats = {
        "level": level,
        "completed": len(ok),
        "failed": failed,
        "wall_s": wall,
        "rps": len(ok) / wall if wall > 0 else 0.0,
        "tok_s": out_total / wall if wall > 0 else 0.0,
        "mean_out_tokens": out_total / len(ok) if ok else 0.0,
        "ttft": ttfts_ms,
        "e2e": e2es_ms,
        "itl": itls_ms,
        "first_error": next((r.error for r in results if not r.ok), ""),
    }

    print(f"\n--- 结果 (并发 {level}) ---")
    print(f"成功: {stats['completed']}  失败: {stats['failed']}  总耗时: {wall:.2f}s")
    if stats["first_error"]:
        print(f"首个错误: {stats['first_error'][:200]}")
    print(f"请求吞吐: {stats['rps']:.2f} req/s")
    print(f"输出吞吐: {stats['tok_s']:.1f} tok/s")
    print(f"平均输出: {stats['mean_out_tokens']:.1f} tokens/请求")
    print(f"TTFT  (ms): {fmt_ms(ttfts_ms)}")
    print(f"总延迟(ms): {fmt_ms(e2es_ms)}")
    print(f"ITL   (ms): {fmt_ms(itls_ms)}")
    return stats


def append_csv(path: str, args, s: dict) -> None:
    """追加一行到 csv（不存在则写表头），便于两个模型横向对比"""
    header = [
        "time", "model", "concurrency", "total_requests", "completed", "failed",
        "wall_s", "req_per_s", "out_tok_per_s", "mean_out_tokens",
        "ttft_mean_ms", "ttft_p50_ms", "ttft_p90_ms", "ttft_p95_ms", "ttft_p99_ms",
        "e2e_mean_ms", "e2e_p50_ms", "e2e_p90_ms", "e2e_p95_ms", "e2e_p99_ms",
        "itl_mean_ms", "itl_p50_ms", "itl_p90_ms", "itl_p99_ms",
    ]
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), args.model, s["level"],
        args.total_requests, s["completed"], s["failed"],
        f"{s['wall_s']:.2f}", f"{s['rps']:.3f}", f"{s['tok_s']:.1f}",
        f"{s['mean_out_tokens']:.1f}",
        f"{_mean(s['ttft']):.1f}", f"{pct(s['ttft'], 50):.1f}",
        f"{pct(s['ttft'], 90):.1f}", f"{pct(s['ttft'], 95):.1f}",
        f"{pct(s['ttft'], 99):.1f}",
        f"{_mean(s['e2e']):.1f}", f"{pct(s['e2e'], 50):.1f}",
        f"{pct(s['e2e'], 90):.1f}", f"{pct(s['e2e'], 95):.1f}",
        f"{pct(s['e2e'], 99):.1f}",
        f"{_mean(s['itl']):.2f}", f"{pct(s['itl'], 50):.2f}",
        f"{pct(s['itl'], 90):.2f}", f"{pct(s['itl'], 99):.2f}",
    ]
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(header)
        w.writerow(row)
    print(f"结果已写入 {path}")


def load_prompts(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        prompts = [ln.strip() for ln in f if ln.strip()]
    if not prompts:
        sys.exit(f"prompt 文件 {path} 为空")
    return prompts


def main():
    parser = argparse.ArgumentParser(
        description="LLM 服务性能测试：多档并发下的 TTFT/ITL/吞吐",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000", help="vLLM 服务地址")
    parser.add_argument("--model", required=True, help="模型名，需与 /v1/models 返回的 id 一致")
    parser.add_argument("--concurrency", nargs="+", type=int,
                        default=[1, 5, 10, 20, 30], help="并发档位列表")
    parser.add_argument("--total-requests", type=int, default=100,
                        help="每档并发的总请求数")
    parser.add_argument("--max-tokens", type=int, default=256,
                        help="限制单请求输出长度（保证不同模型可比性）")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="采样温度，0 保证可复现")
    parser.add_argument("--thinking", action="store_true",
                        help="开启思考模式（默认关闭）")
    parser.add_argument("--warmup", type=int, default=3, help="每档并发前预热请求数")
    parser.add_argument("--timeout", type=float, default=600, help="单请求超时（秒）")
    parser.add_argument("--prompt-file", default=None,
                        help="自定义 prompt 文件（每行一个），不传则使用内置混合 prompt 池")
    parser.add_argument("--csv", default=None, help="结果追加写入的 csv 路径")
    args = parser.parse_args()

    if args.total_requests < max(args.concurrency):
        print(f"提示: total-requests({args.total_requests}) < "
              f"最大并发({max(args.concurrency)})，高并发档位实际并发达不到目标值")

    prompts = load_prompts(args.prompt_file) if args.prompt_file else DEFAULT_PROMPTS
    print(f"目标: {args.url}  模型: {args.model}")
    print(f"prompt 池: {len(prompts)} 条（循环使用）  max_tokens: {args.max_tokens}  "
          f"temperature: {args.temperature}  思考模式: {'开' if args.thinking else '关'}")

    check_model_exists(args)

    all_stats = []
    for level in args.concurrency:
        all_stats.append(run_level(args, prompts, level))

    print(f"\n{'=' * 60}\n汇总")
    print(f"{'并发':>4}  {'req/s':>8}  {'tok/s':>9}  {'TTFT p50':>9}  "
          f"{'TTFT p99':>9}  {'E2E p50':>9}  {'E2E p99':>9}  {'失败':>4}")
    for s in all_stats:
        print(f"{s['level']:>4}  {s['rps']:>8.2f}  {s['tok_s']:>9.1f}  "
              f"{pct(s['ttft'], 50):>9.1f}  {pct(s['ttft'], 99):>9.1f}  "
              f"{pct(s['e2e'], 50):>9.1f}  {pct(s['e2e'], 99):>9.1f}  {s['failed']:>4}")

    if args.csv:
        for s in all_stats:
            append_csv(args.csv, args, s)


if __name__ == "__main__":
    main()
