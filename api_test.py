#!/usr/bin/env python3
"""现网请求回放测试脚本：从 Excel「请求」列读取 Python 格式的请求串，并发回放到质检接口。

数据格式：Excel 指定列（默认列名「请求」）每行一个字符串，是现网爬取的 Python dict
repr（单引号、True/False/None），脚本用 ast.literal_eval 解析，并把 return_details
强制置为 True 后 POST 到 url。

用法示例::

    python api_test.py --excel data.xlsx \
        --url http://127.0.0.1:8000/api/v1/check \
        --concurrency 5 --rounds 2 --output results.jsonl

参数说明::
    --excel        Excel 文件路径（.xlsx）
    --sheet        工作表（序号或名称，默认 0 = 第一个）
    --column       列名（默认「请求」）
    --type-column  错误类型列名（默认「问题类型」，列不存在时 error_type 记 null）
    --url          接口完整地址（默认 http://127.0.0.1:8000/api/v1/check）
    --concurrency  并发数（默认 5）
    --rounds       请求轮数：全部数据发完一轮再发下一轮（默认 1）
    --timeout      单请求超时秒数（默认 600）
    --output       结果明细文件路径，JSONL 格式（默认 api_test_results.jsonl）
    --limit        只取前 N 行数据（0 = 全部，用于冒烟）

结果文件::
    明细：<output>，JSONL，每行固定 5 个字段：round/row/status/error_type/resp。
          error_type 为 Excel「问题类型」列的值（每条都记录，列缺失时为 null）。
          resp 为模型返回的压缩结果：
          - final_has_errors：取自 data.summary.content（JSON 串）解析出的 final_has_error
          - accuracy/number/term/summary：各 agent 的错误描述（error_list 各条 error_desc
            拼接）；无错误、字段为空或 key 不存在则不写；syntax 不统计
          请求失败（非 200 / 网络异常）时 resp 为 null
    汇总：<output>.summary.json，总体统计 + 每轮统计（rounds 数组）+ 跨轮一致性检查

依赖::

    pip install requests openpyxl
"""
from __future__ import annotations

import argparse
import ast
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from openpyxl import load_workbook

AGENTS = ("accuracy", "number", "term", "syntax", "summary")   # 内部统计用（含 syntax）
WRITTEN_AGENTS = ("accuracy", "number", "term", "summary")     # 明细 resp 里记录的 agent（不含 syntax）

_thread_local = threading.local()


def get_session() -> requests.Session:
    """每线程一个 Session，复用连接。"""
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
    return _thread_local.session


# ---------------------------------------------------------------- 数据读取

def load_requests(excel_path: str, column: str, type_column: str, sheet: Any,
                  limit: int) -> Tuple[List[Tuple[int, dict, Any]], List[dict]]:
    """读取 Excel 指定列，返回 ([(Excel行号, 请求dict, 问题类型), ...], 解析失败列表)。

    解析成功的请求强制 return_details=True；问题类型列不存在时类型值记 None。
    """
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if isinstance(sheet, str) else wb.worksheets[sheet]
        rows = ws.iter_rows(values_only=True)
        headers = list(next(rows, []))
        try:
            col = headers.index(column)
        except ValueError:
            raise SystemExit(f"找不到列「{column}」，实际表头: {headers}")
        type_col = headers.index(type_column) if type_column in headers else None
        if type_col is None:
            print(f"⚠ 未找到问题类型列「{type_column}」，error_type 将记为 null")

        items: List[Tuple[int, dict, Any]] = []
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
            payload["return_details"] = True
            error_type = row[type_col] if type_col is not None and type_col < len(row) else None
            items.append((row_no, payload, error_type))
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


# ---------------------------------------------------------------- 请求与结果提取

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


def _join_desc(error_list: Any) -> Optional[str]:
    """拼接 error_list 各条的 error_desc；无有效描述返回 None。"""
    if not isinstance(error_list, list):
        return None
    descs = [d.strip() for e in error_list
             if isinstance(e, dict) and (d := (e.get("error_desc") or "")).strip()]
    return "\n".join(descs) if descs else None


def _agent_desc(content: Any) -> Optional[str]:
    """从单个 agent 的 content（JSON 串）提取错误描述；无错/解析失败返回 None。"""
    if not isinstance(content, str) or not content:
        return None
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    return _join_desc(parsed.get("error_list"))


def extract_result(resp: Any) -> Tuple[Optional[dict], dict]:
    """把接口响应提取成 (明细resp, 内部统计)。

    明细resp：{final_has_errors, accuracy?, number?, term?, summary}——
    final_has_errors 取自 data.summary.content 解析结果的 final_has_error
    （content 为空/非 JSON/键缺失时为 null，原因记入统计）；accuracy/number/term
    的错误描述无值则不写；summary 描述无条件写入（无值记 null）；syntax 不统计。
    响应非法时返回 (None, 统计)。
    """
    stats: Dict[str, Any] = {"check_success": None, "final_has_error": None,
                             "error_count": 0, "agent_failures": [], "null_cause": None}
    if not isinstance(resp, dict):
        return None, stats
    data = resp.get("data") or {}
    stats["check_success"] = data.get("success")
    for t in AGENTS:
        a = data.get(t)
        if isinstance(a, dict) and a.get("success") is False:
            stats["agent_failures"].append(f"{t}: {a.get('error')}")

    summary = data.get("summary")
    content = summary.get("content") if isinstance(summary, dict) else summary
    summary_parsed = None
    if isinstance(content, str) and content:
        try:
            summary_parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            summary_parsed = None

    detail: Dict[str, Any] = {}
    if isinstance(summary_parsed, dict):
        fhe = summary_parsed.get("final_has_error", summary_parsed.get("final_has_errors"))
        stats["final_has_error"] = fhe
        error_list = summary_parsed.get("error_list") or []
        stats["error_count"] = len(error_list)
        detail["final_has_errors"] = fhe
        if fhe is None and "final_has_error" not in summary_parsed and "final_has_errors" not in summary_parsed:
            stats["null_cause"] = "final_has_error键缺失"
    else:
        detail["final_has_errors"] = None
        stats["null_cause"] = ("summary的content为空或缺失" if not (isinstance(content, str) and content)
                               else "summary的content非合法JSON")
    for t in WRITTEN_AGENTS[:-1]:                     # accuracy / number / term
        a = data.get(t)
        src = a.get("content") if isinstance(a, dict) else None
        desc = _agent_desc(src)
        if desc:
            detail[t] = desc
    detail["summary"] = _join_desc(summary_parsed.get("error_list")) if isinstance(summary_parsed, dict) else None
    return detail, stats


# ---------------------------------------------------------------- 轮次执行

def run_round(url: str, items: List[Tuple[int, dict, Any]], concurrency: int, timeout: float,
              round_no: int, rounds: int, out_file) -> Tuple[List[dict], float]:
    """并发发送一轮，逐条写入明细文件，返回 (结果列表, 耗时秒)。

    明细行固定 5 个字段：round/row/status/error_type/resp（resp 为提取后的模型结果）；
    ok/latency/错误信息/统计挂在内存结果的下划线键下，仅供汇总与进度，不落盘。
    """
    results: List[dict] = []
    total = len(items)
    step = max(1, total // 10)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(send_one, url, payload, timeout): (row_no, error_type)
                   for row_no, payload, error_type in items}
        for done, fut in enumerate(as_completed(futures), 1):
            row_no, error_type = futures[fut]
            rec = fut.result()
            detail, stats = extract_result(rec["resp"]) if rec["ok"] else (None, _EMPTY_STATS())
            item: Dict[str, Any] = {"round": round_no, "row": row_no,
                                    "status": rec["status"], "error_type": error_type,
                                    "resp": detail,
                                    "_ok": rec["ok"], "_latency_ms": rec["latency_ms"],
                                    "_error": rec["error"], "_stats": stats}
            results.append(item)
            out_file.write(json.dumps(
                {"round": item["round"], "row": item["row"], "status": item["status"],
                 "error_type": item["error_type"], "resp": item["resp"]},
                ensure_ascii=False) + "\n")
            out_file.flush()
            if done % step == 0 or done == total:
                lat = [r["_latency_ms"] for r in results if r["_latency_ms"] is not None]
                avg = round(sum(lat) / len(lat) / 1000, 1) if lat else "-"
                print(f"  [轮 {round_no}/{rounds}] {done}/{total} 完成，"
                      f"失败 {sum(1 for r in results if not r['_ok'])}，均耗 {avg}s", flush=True)
    return results, time.time() - t0


def _EMPTY_STATS() -> dict:
    return {"check_success": None, "final_has_error": None,
            "error_count": 0, "agent_failures": [], "null_cause": None}


def summarize(results: List[dict], duration: float) -> dict:
    ok = [r for r in results if r["_ok"]]
    lat = sorted(r["_latency_ms"] for r in ok if r["_latency_ms"] is not None)

    def pct(p: float) -> Optional[int]:
        return lat[min(len(lat) - 1, int(len(lat) * p))] if lat else None

    null_causes: Dict[str, int] = {}
    for r in ok:
        cause = r["_stats"].get("null_cause")
        if r["_stats"].get("final_has_error") is None and cause:
            null_causes[cause] = null_causes.get(cause, 0) + 1

    return {
        "requests": len(results),
        "http_ok": len(ok),
        "http_fail": len(results) - len(ok),
        "check_success": sum(1 for r in ok if r["_stats"].get("check_success") is True),
        "has_error": sum(1 for r in ok if r["_stats"].get("final_has_error") is True),
        "final_null": sum(1 for r in ok if r["_stats"].get("final_has_error") is None),
        "final_null_causes": null_causes,
        "error_count_total": sum(r["_stats"].get("error_count") or 0 for r in ok),
        "agent_failures": sum(1 for r in ok if r["_stats"].get("agent_failures")),
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
        if not r["_ok"] or r["resp"] is None:
            continue
        by_row.setdefault(r["row"], set()).add(
            json.dumps(r["resp"], ensure_ascii=False, sort_keys=True))
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
    ap.add_argument("--type-column", default="问题类型",
                    help="错误类型列名（默认「问题类型」，列不存在时 error_type 记 null）")
    ap.add_argument("--url", default="http://127.0.0.1:8000/api/v1/check",
                    help="接口完整地址")
    ap.add_argument("--concurrency", type=int, default=5, help="并发数（默认 5）")
    ap.add_argument("--rounds", type=int, default=1, help="请求轮数（默认 1）")
    ap.add_argument("--timeout", type=float, default=600, help="单请求超时秒数（默认 600）")
    ap.add_argument("--output", default="api_test_results.jsonl",
                    help="结果明细文件路径（JSONL）")
    ap.add_argument("--limit", type=int, default=0, help="只取前 N 行（0=全部）")
    args = ap.parse_args()

    sheet: Any = int(args.sheet) if args.sheet.isdigit() else args.sheet
    print(f"读取 {args.excel} [sheet={sheet}] 列「{args.column}」 ...")
    items, bad = load_requests(args.excel, args.column, args.type_column, sheet, args.limit)
    print(f"有效请求 {len(items)} 条（已强制 return_details=True），解析失败 {len(bad)} 条")
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
    round_stats: List[dict] = []
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(out_path, "w", encoding="utf-8") as out_file:
            for round_no in range(1, args.rounds + 1):
                print(f"===== 第 {round_no}/{args.rounds} 轮：{len(items)} 条，"
                      f"并发 {args.concurrency} =====", flush=True)
                results, duration = run_round(
                    args.url, items, args.concurrency, args.timeout,
                    round_no, args.rounds, out_file)
                all_results.extend(results)
                stats = summarize(results, duration)
                round_stats.append({"round": round_no, **stats})
                print(f"----- 第 {round_no} 轮统计 -----")
                print(json.dumps(stats, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("\n⚠ 中断：明细已写入（逐条落盘），以下为部分汇总")

    final = {
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"excel": args.excel, "column": args.column, "url": args.url,
                   "concurrency": args.concurrency, "rounds": args.rounds,
                   "timeout": args.timeout, "limit": args.limit,
                   "return_details_forced": True},
        "valid_requests": len(items),
        "parse_failures": bad,
        "rounds": round_stats,
        "total": summarize(all_results, 0) if all_results else None,
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
