#!/usr/bin/env python3
"""现网请求回放测试脚本：从 Excel「请求」列读取 Python 格式的请求串，并发回放到质检接口。

数据格式：Excel 指定列（默认列名「请求」）每行一个字符串，是现网爬取的 Python dict
repr（单引号、True/False/None），脚本用 ast.literal_eval 解析后原样 POST 到 url。

用法示例::

    python api_test.py --excel data.xlsx \
        --url http://127.0.0.1:8000/api/v1/check \
        --concurrency 5 --rounds 2 --output results.jsonl

参数说明::
    --excel        Excel 文件路径（.xlsx）
    --sheet        工作表（序号或名称，默认 0 = 第一个）
    --column       列名（默认「请求」）
    --url          接口完整地址（默认 http://127.0.0.1:8000/api/v1/check）
    --concurrency  并发数（默认 5）
    --rounds       请求轮数：全部数据发完一轮再发下一轮（默认 1）
    --timeout      单请求超时秒数（默认 600）
    --output       结果明细文件路径，JSONL 格式，一行一个请求结果（默认 api_test_results.jsonl）
    --limit        只取前 N 行数据（0 = 全部，用于冒烟）
    --save-full    明细中额外保存完整响应体（默认只存摘要，文件会小很多）

结果文件::
    明细：<output>，JSONL，每行含 round/row/ok/status/latency_ms/check_success/
          final_has_error/error_count/errors/agent_failures 等
    汇总：<output>.summary.json，总体统计 + 各轮统计 + 跨轮一致性检查

依赖::

    pip install requests openpyxl
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from openpyxl import load_workbook

AGENTS = ("accuracy", "number", "term", "syntax", "summary")

_thread_local = threading.local()


def get_session() -> requests.Session:
    """每线程一个 Session，复用连接。"""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
    return _thread_local.session


# ---------------------------------------------------------------- 数据读取

def load_requests(excel_path: str, column: str, sheet: Any,
                  limit: int) -> Tuple[List[Tuple[int, dict]], List[dict]]:
    """读取 Excel 指定列，返回 ([(Excel行号, 请求dict), ...], 解析失败列表)。"""
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if isinstance(sheet, str) else wb.worksheets[sheet]
        rows = ws.iter_rows(values_only=True)
        headers = list(next(rows, []))
        try:
            col = headers.index(column)
        except ValueError:
            raise SystemExit(f"找不到列「{column}」，实际表头: {headers}")

        items: List[Tuple[int, dict]] = []
        bad: List[dict] = []
        for row_no, row in enumerate(rows, start=2):  # 表头为第1行，数据从第2行起
            if limit and len(items) >= limit:
                break
            cell = row[col] if col < len(row) else None
            if cell is None or (isinstance(cell, str) and not cell.strip()):
                bad.append({"row": row_no, "error": "空单元格"})
                continue
            text = str(cell).strip()
            payload, err = _parse_payload(text)
            if not isinstance(payload, dict):
                bad.append({"row": row_no, "error": err or f"非dict: {type(payload).__name__}",
                            "text_head": text[:120]})
                continue
            items.append((row_no, payload))
        return items, bad
    finally:
        wb.close()


def _parse_payload(text: str) -> Tuple[Optional[Any], Optional[str]]:
    """解析单元格文本：优先按 Python 字面量（单引号/False/None），失败再试标准 JSON。"""
    try:
        return ast.literal_eval(text), None
    except (ValueError, SyntaxError) as e:
        try:
            return json.loads(text), None
        except json.JSONDecodeError:
            return None, f"literal_eval/loads 均失败: {e}"


# ---------------------------------------------------------------- 请求与解析

def send_one(url: str, payload: dict, timeout: float) -> dict:
    """发送单个请求，返回 {ok, status, latency_ms, error, resp}。"""
    rec: Dict[str, Any] = {"ok": False, "status": None, "latency_ms": None,
                           "error": None, "resp": None}
    t0 = time.time()
    try:
        r = get_session().post(url, json=payload, timeout=timeout)
        rec["status"] = r.status_code
        rec["latency_ms"] = round((time.time() - t0) * 1000)
        if r.status_code != 200:
            rec["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
        else:
            rec["resp"] = r.json()
            rec["ok"] = True
    except requests.exceptions.Timeout as e:
        rec["error"] = f"timeout: {e}"
    except requests.exceptions.RequestException as e:
        rec["error"] = f"request: {e}"
    except ValueError as e:
        rec["error"] = f"resp not json: {e}"
    return rec


def parse_response(resp: Any) -> dict:
    """把接口响应压缩成结果摘要（兼容 /check 与 /check/simple 两种响应形态）。"""
    out: Dict[str, Any] = {"api_success": None, "check_success": None,
                           "final_has_error": None, "error_count": 0,
                           "errors": [], "agent_failures": [], "summary_error": None}
    if not isinstance(resp, dict):
        out["summary_error"] = f"非dict响应: {str(resp)[:200]}"
        return out
    out["api_success"] = resp.get("success")
    data = resp.get("data") or {}
    out["check_success"] = data.get("success")
    for t in AGENTS:
        a = data.get(t)
        if isinstance(a, dict) and a.get("success") is False:
            out["agent_failures"].append(f"{t}: {a.get('error')}")
    summary = data.get("summary")
    content = summary.get("content") if isinstance(summary, dict) else summary
    if isinstance(content, str) and content:
        try:
            parsed = json.loads(content)
            out["final_has_error"] = parsed.get("final_has_error")
            error_list = parsed.get("error_list") or []
            out["error_count"] = len(error_list)
            out["errors"] = [
                {"severity": e.get("severity"), "sources": e.get("sources"),
                 "desc": (e.get("error_desc") or "")[:200],
                 "src": (e.get("source_full_line") or "")[:80]}
                for e in error_list if isinstance(e, dict)
            ]
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            out["summary_error"] = f"summary解析失败: {e}; content前200: {content[:200]}"
    return out


# ---------------------------------------------------------------- 轮次执行

def run_round(url: str, items: List[Tuple[int, dict]], concurrency: int, timeout: float,
              round_no: int, rounds: int, out_file, save_full: bool) -> Tuple[List[dict], float]:
    """并发发送一轮，逐条写入明细文件，返回 (结果列表, 耗时秒)。"""
    results: List[dict] = []
    total = len(items)
    step = max(1, total // 10)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(send_one, url, payload, timeout): row_no
                   for row_no, payload in items}
        for done, fut in enumerate(as_completed(futures), 1):
            row_no = futures[fut]
            rec = fut.result()
            item: Dict[str, Any] = {"round": round_no, "row": row_no,
                                    "ok": rec["ok"], "status": rec["status"],
                                    "latency_ms": rec["latency_ms"], "error": rec["error"]}
            item.update(parse_response(rec["resp"]) if rec["ok"] else parse_response(None))
            if save_full and rec["ok"]:
                item["raw"] = rec["resp"]
            results.append(item)
            out_file.write(json.dumps(item, ensure_ascii=False) + "\n")
            out_file.flush()
            if done % step == 0 or done == total:
                lat = [r["latency_ms"] for r in results if r["latency_ms"] is not None]
                avg = round(sum(lat) / len(lat) / 1000, 1) if lat else "-"
                print(f"  [轮 {round_no}/{rounds}] {done}/{total} 完成，"
                      f"失败 {sum(1 for r in results if not r['ok'])}，均耗 {avg}s", flush=True)
    return results, time.time() - t0


def summarize(results: List[dict], duration: float) -> dict:
    ok = [r for r in results if r["ok"]]
    lat = sorted(r["latency_ms"] for r in ok if r["latency_ms"] is not None)

    def pct(p: float) -> Optional[int]:
        return lat[min(len(lat) - 1, int(len(lat) * p))] if lat else None

    return {
        "requests": len(results),
        "http_ok": len(ok),
        "http_fail": len(results) - len(ok),
        "check_success": sum(1 for r in ok if r.get("check_success")),
        "has_error": sum(1 for r in ok if r.get("final_has_error")),
        "error_count_total": sum(r.get("error_count") or 0 for r in ok),
        "agent_failures": sum(1 for r in ok if r.get("agent_failures")),
        "summary_parse_fail": sum(1 for r in ok if r.get("summary_error")),
        "latency_ms": {"avg": round(sum(lat) / len(lat)) if lat else None,
                       "p50": pct(0.5), "p95": pct(0.95),
                       "max": lat[-1] if lat else None},
        "duration_s": round(duration, 1),
        "throughput_per_min": round(len(results) / duration * 60, 2) if duration else None,
    }


def cross_round_consistency(results: List[dict]) -> dict:
    """多轮时检查同一条数据跨轮结果是否一致（temperature=0 + seed=42 理论上应一致）。"""
    by_row: Dict[int, set] = {}
    for r in results:
        if not r["ok"]:
            continue
        key = json.dumps({"final_has_error": r.get("final_has_error"),
                          "errors": r.get("errors")}, ensure_ascii=False, sort_keys=True)
        by_row.setdefault(r["row"], set()).add(key)
    inconsistent = sorted(row for row, keys in by_row.items() if len(keys) > 1)
    return {"rows_compared": len(by_row),
            "inconsistent_rows": len(inconsistent),
            "inconsistent_examples": inconsistent[:10]}


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser(description="Excel 请求回放测试脚本")
    ap.add_argument("--excel", required=True, help="Excel 文件路径（.xlsx）")
    ap.add_argument("--sheet", default="0", help="工作表序号或名称（默认 0）")
    ap.add_argument("--column", default="请求", help="列名（默认「请求」）")
    ap.add_argument("--url", default="http://127.0.0.1:8000/api/v1/check",
                    help="接口完整地址")
    ap.add_argument("--concurrency", type=int, default=5, help="并发数（默认 5）")
    ap.add_argument("--rounds", type=int, default=1, help="请求轮数（默认 1）")
    ap.add_argument("--timeout", type=float, default=600, help="单请求超时秒数（默认 600）")
    ap.add_argument("--output", default="api_test_results.jsonl",
                    help="结果明细文件路径（JSONL）")
    ap.add_argument("--limit", type=int, default=0, help="只取前 N 行（0=全部）")
    ap.add_argument("--save-full", action="store_true", help="明细中保存完整响应体")
    args = ap.parse_args()

    sheet: Any = int(args.sheet) if args.sheet.isdigit() else args.sheet
    print(f"读取 {args.excel} [sheet={sheet}] 列「{args.column}」 ...")
    items, bad = load_requests(args.excel, args.column, sheet, args.limit)
    print(f"有效请求 {len(items)} 条，解析失败 {len(bad)} 条")
    for b in bad[:10]:
        print(f"  ⚠ 第{b['row']}行: {b['error']}")
    if bad:
        print(f"  （共 {len(bad)} 条失败，仅展示前 10）")
    if not items:
        print("无有效请求数据，退出")
        return

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    all_results: List[dict] = []
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(out_path, "w", encoding="utf-8") as out_file:
            for round_no in range(1, args.rounds + 1):
                print(f"===== 第 {round_no}/{args.rounds} 轮：{len(items)} 条，"
                      f"并发 {args.concurrency} =====", flush=True)
                results, duration = run_round(
                    args.url, items, args.concurrency, args.timeout,
                    round_no, args.rounds, out_file, args.save_full)
                all_results.extend(results)
                print(f"----- 第 {round_no} 轮统计 -----")
                print(json.dumps(summarize(results, duration), ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("\n⚠ 中断：明细已写入（逐条落盘），以下为部分汇总")

    final = {
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"excel": args.excel, "column": args.column, "url": args.url,
                   "concurrency": args.concurrency, "rounds": args.rounds,
                   "timeout": args.timeout, "limit": args.limit},
        "valid_requests": len(items),
        "parse_failures": bad,
        "total": summarize(all_results, 0) if all_results else None,
        "per_round_note": "明细文件中按 round 字段区分各轮",
    }
    if args.rounds > 1 and all_results:
        final["cross_round_consistency"] = cross_round_consistency(all_results)

    summary_path = Path(str(out_path) + ".summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    print(f"\n明细: {out_path}")
    print(f"汇总: {summary_path}")


if __name__ == "__main__":
    main()
