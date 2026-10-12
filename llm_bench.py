#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 推理服务性能测试脚本（零依赖，仅 Python 标准库）

测试指定并发数下的端到端延迟 / 吞吐量（滑动窗口式持续并发：
某档并发 N 时，任何时刻都保持恰好 N 个请求在途，完成一个立刻补一个）。
所有请求均为：非流式 + temperature=0 + 禁止思考。

用法: 直接修改下方"配置区"后运行
    python3 llm_bench.py
    python3 llm_bench.py --concurrency 1 5 10 --csv result.csv   # 临时覆盖部分参数
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

# ==================== 配置区（直接改这里） ====================
URL = "http://localhost:8000/v1/chat/completions"  # 推理接口完整地址
MODELS_URL = "http://localhost:8000/v1/models"     # 模型列表接口完整地址
MODEL = "qwen3.5-27B"                              # 模型名，与 /v1/models 返回的 id 一致

# 所有请求（含模型列表查询）统一携带的 header
HEADERS = {
    "Content-Type": "application/json",
    # "Authorization": "Bearer EMPTY",  # 服务有鉴权时取消注释并填写
}

START_DELAY = 0  # 启动脚本后延迟多少秒再正式开始测试，0 = 立即开始
# ==============================================================


# ---------------------------------------------------------------------------
# 固定 prompt 池：两个模型循环使用完全相同的输入，保证测试公平、可复现。
# 刻意混合了短问答 / 数学推理 / 代码 / 翻译 / 长文本摘要 / 英文等任务，
# 同时包含长短不同的输入（影响 prefill 耗时）。
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

TEMPERATURE = 0.0  # 固定温度 0，保证可复现


@dataclass
class ReqResult:
    ok: bool = False
    error: str = ""
    e2e_s: float | None = None  # 端到端延迟（秒）
    output_tokens: int = 0


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


def _mean(vals: list) -> float:
    return sum(vals) / len(vals) if vals else float("nan")


def fmt_ms(vals: list) -> str:
    return (
        f"mean={_mean(vals):8.1f}  "
        f"p50={pct(vals, 50):8.1f}  p90={pct(vals, 90):8.1f}  "
        f"p95={pct(vals, 95):8.1f}  p99={pct(vals, 99):8.1f}"
    )


def post_json(url: str, payload: dict, timeout: float) -> tuple[int, bytes]:
    """POST JSON，携带配置区 HEADERS，返回 (状态码, 响应体)"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get_json(url: str, timeout: float) -> tuple[int, bytes]:
    """GET，携带配置区 HEADERS，返回 (状态码, 响应体)"""
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def build_payload(model: str, prompt: str, max_tokens: int, fixed_output: bool = True) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if fixed_output:
        # 强制每个请求恰好生成 max_tokens 个 token（不会提前停止），
        # 保证两个模型输出量完全一致，E2E / req/s / tok/s 均可直接对比
        payload["min_tokens"] = max_tokens
    # Qwen3 系列模板使用 enable_thinking，DeepSeek 系列使用 thinking；
    # vLLM 会自动过滤当前模型模板不支持的变量，两个都传是安全的。
    payload["chat_template_kwargs"] = {"enable_thinking": False, "thinking": False}
    return payload


def check_model_exists(args) -> None:
    """启动后先校验模型名，避免白白跑一轮"""
    try:
        status, raw = get_json(args.models_url, timeout=10)
        if status != 200:
            print(f"[check] 查询模型列表返回 HTTP {status}，跳过校验")
            return
        data = json.loads(raw.decode("utf-8"))
        ids = [m.get("id") for m in data.get("data", [])]
        if args.model in ids:
            print(f"[check] 模型 '{args.model}' 已在服务端加载 ✓")
        else:
            print(f"[check] 警告: 模型 '{args.model}' 不在服务列表中 {ids}，"
                  f"请求可能返回 404，请核对 /v1/models 返回的 id")
    except Exception as e:
        print(f"[check] 无法查询模型列表: {e!r}")


def send_one(args, prompt: str) -> ReqResult:
    """发送单个非流式请求，记录端到端延迟和输出 token 数"""
    result = ReqResult()
    payload = build_payload(args.model, prompt, args.max_tokens,
                            fixed_output=not args.no_fixed_output)
    start = time.perf_counter()
    status, raw = post_json(args.url, payload, args.timeout)
    result.e2e_s = time.perf_counter() - start

    if status != 200:
        result.error = f"HTTP {status}: {raw[:200].decode('utf-8', 'replace')}"
        return result
    try:
        data = json.loads(raw.decode("utf-8"))
        usage = data.get("usage") or {}
        output_tokens = usage.get("completion_tokens")
        choices = data.get("choices") or []
        content = ""
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
        if output_tokens is None:
            result.error = "响应中缺少 usage.completion_tokens"
        elif output_tokens == 0 and not content:
            result.error = "模型没有输出任何内容"
        else:
            result.output_tokens = output_tokens
            result.ok = True
    except Exception as e:
        result.error = repr(e)
    return result


def warmup(args) -> None:
    """每档并发前发送少量小请求预热（不计入统计）"""
    for i in range(args.warmup):
        payload = build_payload(args.model, DEFAULT_PROMPTS[i % len(DEFAULT_PROMPTS)],
                                max_tokens=4, fixed_output=False)
        try:
            status, _ = post_json(args.url, payload, args.timeout)
            if status != 200:
                print(f"[warmup] 第 {i + 1} 个预热请求返回 HTTP {status}")
        except Exception as e:
            print(f"[warmup] 预热请求失败: {e!r}")


def run_level(args, prompts: list, level: int) -> dict:
    total = (args.total_requests if args.total_requests is not None
             else level * args.requests_per_concurrency)
    print(f"\n{'=' * 60}")
    print(f"并发数 = {level}，总请求数 = {total}")
    print("=" * 60)

    if args.warmup > 0:
        print(f"预热中（{args.warmup} 个请求）...")
        warmup(args)

    results: list[ReqResult] = []
    lock = threading.Lock()
    state = {"next_idx": 0, "done": 0}

    def worker():
        """常驻 worker：发完一个请求立即取下一个，保持并发水位不下降"""
        while True:
            with lock:
                idx = state["next_idx"]
                if idx >= total:
                    return
                state["next_idx"] += 1
            r = send_one(args, prompts[idx % len(prompts)])
            with lock:
                results.append(r)
                state["done"] += 1
                if state["done"] % 10 == 0 or state["done"] == total:
                    print(f"  进度 {state['done']}/{total}", flush=True)

    threads = [threading.Thread(target=worker) for _ in range(level)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - start

    ok = [r for r in results if r.ok]
    failed = len(results) - len(ok)
    e2es_ms = [r.e2e_s * 1000 for r in ok]
    out_total = sum(r.output_tokens for r in ok)

    stats = {
        "level": level,
        "total": total,
        "completed": len(ok),
        "failed": failed,
        "wall_s": wall,
        "rps": len(ok) / wall if wall > 0 else 0.0,
        "tok_s": out_total / wall if wall > 0 else 0.0,
        "mean_out_tokens": out_total / len(ok) if ok else 0.0,
        "e2e": e2es_ms,
        "first_error": next((r.error for r in results if not r.ok), ""),
    }

    print(f"\n--- 结果 (并发 {level}) ---")
    print(f"成功: {stats['completed']}  失败: {stats['failed']}  总耗时: {wall:.2f}s")
    if stats["first_error"]:
        print(f"首个错误: {stats['first_error'][:200]}")
    print(f"请求吞吐: {stats['rps']:.2f} req/s")
    print(f"输出吞吐: {stats['tok_s']:.1f} tok/s")
    print(f"平均输出: {stats['mean_out_tokens']:.1f} tokens/请求")
    print(f"E2E延迟(ms): {fmt_ms(e2es_ms)}")
    return stats


def append_csv(path: str, args, s: dict) -> None:
    """追加一行到 csv（不存在则写表头），便于两个模型横向对比"""
    header = [
        "time", "model", "concurrency", "total_requests", "completed", "failed",
        "wall_s", "req_per_s", "out_tok_per_s", "mean_out_tokens",
        "e2e_mean_ms", "e2e_p50_ms", "e2e_p90_ms", "e2e_p95_ms", "e2e_p99_ms",
    ]
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), args.model, s["level"],
        s["total"], s["completed"], s["failed"],
        f"{s['wall_s']:.2f}", f"{s['rps']:.3f}", f"{s['tok_s']:.1f}",
        f"{s['mean_out_tokens']:.1f}",
        f"{_mean(s['e2e']):.1f}", f"{pct(s['e2e'], 50):.1f}",
        f"{pct(s['e2e'], 90):.1f}", f"{pct(s['e2e'], 95):.1f}",
        f"{pct(s['e2e'], 99):.1f}",
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
        description="LLM 服务性能测试：非流式 + 温度0 + 禁止思考，多档并发下的延迟/吞吐",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--url", default=URL, help="推理接口完整地址（默认取脚本顶部配置）")
    parser.add_argument("--models-url", default=MODELS_URL,
                        help="模型列表接口完整地址（默认取脚本顶部配置）")
    parser.add_argument("--model", default=MODEL,
                        help="模型名，需与 /v1/models 返回的 id 一致（默认取脚本顶部配置）")
    parser.add_argument("--concurrency", nargs="+", type=int,
                        default=[1, 5, 10, 20, 30], help="并发档位列表")
    parser.add_argument("--total-requests", type=int, default=None,
                        help="每档并发固定总请求数；不传则动态取 并发数 × "
                             "requests-per-concurrency")
    parser.add_argument("--requests-per-concurrency", type=int, default=20,
                        help="未指定 --total-requests 时，每档总请求数 = 并发数 × 该倍数")
    parser.add_argument("--max-tokens", type=int, default=256,
                        help="限制单请求输出长度（保证不同模型可比性）")
    parser.add_argument("--no-fixed-output", action="store_true",
                        help="不强制 min_tokens=max_tokens，允许模型自然提前停止"
                             "（此时两模型输出量可能不同，E2E 不可比）")
    parser.add_argument("--warmup", type=int, default=3, help="每档并发前预热请求数")
    parser.add_argument("--timeout", type=float, default=600, help="单请求超时（秒）")
    parser.add_argument("--prompt-file", default=None,
                        help="自定义 prompt 文件（每行一个），不传则使用内置混合 prompt 池")
    parser.add_argument("--start-delay", type=int, default=START_DELAY,
                        help="启动脚本后延迟多少秒再开始测试（默认取脚本顶部配置）")
    parser.add_argument("--csv", default=None, help="结果追加写入的 csv 路径")
    args = parser.parse_args()

    if args.start_delay > 0:
        print(f"[定时] 将在 {args.start_delay} 秒后开始测试...")
        for remaining in range(args.start_delay, 0, -1):
            print(f"\r[定时] 剩余 {remaining:5d} 秒", end="", flush=True)
            time.sleep(1)
        print("\r[定时] 时间到，开始测试          ")

    if args.total_requests is not None and args.total_requests < max(args.concurrency):
        print(f"提示: total-requests({args.total_requests}) < "
              f"最大并发({max(args.concurrency)})，高并发档位实际并发达不到目标值")

    prompts = load_prompts(args.prompt_file) if args.prompt_file else DEFAULT_PROMPTS
    print(f"目标: {args.url}  模型: {args.model}")
    if args.total_requests is not None:
        print(f"每档总请求数: 固定 {args.total_requests}")
    else:
        print(f"每档总请求数: 动态 = 并发数 × {args.requests_per_concurrency} "
              f"（如并发 1→{1 * args.requests_per_concurrency}，"
              f"并发 30→{30 * args.requests_per_concurrency}）")
    print(f"模式: 非流式  temperature: {TEMPERATURE}  思考模式: 关  "
          f"prompt 池: {len(prompts)} 条（循环使用）  max_tokens: {args.max_tokens}  "
          f"输出长度: {'固定 ' + str(args.max_tokens) + ' tokens' if not args.no_fixed_output else '自然停止'}")

    check_model_exists(args)

    all_stats = []
    for level in args.concurrency:
        all_stats.append(run_level(args, prompts, level))

    print(f"\n{'=' * 60}\n汇总")
    print(f"{'并发':>4}  {'req/s':>8}  {'tok/s':>9}  {'E2E p50':>9}  "
          f"{'E2E p90':>9}  {'E2E p99':>9}  {'失败':>4}")
    for s in all_stats:
        print(f"{s['level']:>4}  {s['rps']:>8.2f}  {s['tok_s']:>9.1f}  "
              f"{pct(s['e2e'], 50):>9.1f}  {pct(s['e2e'], 90):>9.1f}  "
              f"{pct(s['e2e'], 99):>9.1f}  {s['failed']:>4}")

    if args.csv:
        for s in all_stats:
            append_csv(args.csv, args, s)


if __name__ == "__main__":
    main()
