"""boogu_server.py 接口测试脚本(支持单请求 / 持续并发压测).

依赖: pip install requests

用法:
    python test_boogu_server.py                                          # 单请求,generate+edit 各测一次
    python test_boogu_server.py --mode edit                              # 单请求,只测编辑
    python test_boogu_server.py --mode generate --concurrency 10 --total 50
                                                                        # 10 并发持续压测 50 条(滑动补位,
                                                                        #  不等整批结束)

说明:
    - 持续并发:线程池保持 N 个在途请求,任何一个完成立即补下一个(非分批等待)
    - 服务端 pipeline 全局锁串行生成,并发测试下 client 延时 = 排队 + 生成
    - 结果图片按序号保存: <output-dir>/<mode>_0000.png ...
"""

import argparse
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

DEFAULT_T2I_PROMPT = "A cinematic mountain landscape illuminated by golden light."
DEFAULT_EDIT_PROMPT = "Replace the background with a beach while preserving the subject."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="boogu_server test client")

    parser.add_argument("--server", type=str, default="http://127.0.0.1:8090")
    parser.add_argument("--mode", type=str, default="both", choices=["generate", "edit", "both"],
                        help="generate=文生图, edit=图像编辑, both=两者各测一次(仅限单请求)")
    parser.add_argument("--concurrency", type=int, default=1, help="并发数(持续并发,完成即补位)")
    parser.add_argument("--total", type=int, default=1, help="总请求数")
    parser.add_argument("--prompt", type=str, default=None,
                        help="不传则用各模式默认 prompt")
    parser.add_argument("--image", type=str, default="input_image_examples/03.jpg",
                        help="edit 模式输入图片路径")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=-1,
                        help="-1=每条请求随机;固定值则所有请求同 seed")
    parser.add_argument("--output-dir", type=str, default="outputs/test_results")
    parser.add_argument("--timeout", type=int, default=600, help="单请求读取超时(秒)")
    return parser.parse_args()


def health_check(server: str) -> bool:
    print(f"[health] GET {server}/health ...")
    try:
        resp = requests.get(f"{server}/health", timeout=(5, 10))
        resp.raise_for_status()
        print(f"[health] {resp.json()}")
        return True
    except Exception as exc:
        print(f"[health] FAILED: {exc}")
        return False


def do_request(mode: str, idx: int, args, image_bytes: bytes, prompt: str) -> dict:
    url = f"{args.server}/v1/images/{'generations' if mode == 'generate' else 'edits'}"
    seed = args.seed if args.seed >= 0 else random.randint(0, 2**31 - 1)
    t0 = time.time()
    try:
        if mode == "generate":
            payload = {
                "prompt": prompt,
                "width": args.width,
                "height": args.height,
                "seed": seed,
                "format": "png",
            }
            resp = requests.post(url, json=payload, timeout=(5, args.timeout))
        else:
            files = {"image": (os.path.basename(args.image), image_bytes, "image/jpeg")}
            data = {
                "prompt": prompt,
                "width": str(args.width),
                "height": str(args.height),
                "seed": str(seed),
                "format": "png",
            }
            resp = requests.post(url, files=files, data=data, timeout=(5, args.timeout))
        latency = time.time() - t0

        if resp.status_code == 200:
            out_path = os.path.join(args.output_dir, f"{mode}_{idx:04d}.png")
            with open(out_path, "wb") as f:
                f.write(resp.content)
            gen_time = resp.headers.get("X-Generation-Time")
            return {
                "idx": idx, "ok": True, "latency": latency, "status": 200,
                "out": out_path, "seed": resp.headers.get("X-Seed"),
                "server_time": float(gen_time.rstrip("s")) if gen_time else None,
                "error": None,
            }
        return {
            "idx": idx, "ok": False, "latency": latency,
            "status": resp.status_code, "error": resp.text[:200],
            "server_time": None,
        }
    except Exception as exc:
        return {
            "idx": idx, "ok": False, "latency": time.time() - t0,
            "status": -1, "error": str(exc), "server_time": None,
        }


def percentile(sorted_vals, p: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def run_test(mode: str, args, image_bytes: bytes) -> None:
    prompt = args.prompt or (DEFAULT_T2I_PROMPT if mode == "generate" else DEFAULT_EDIT_PROMPT)
    total = args.total
    concurrency = min(args.concurrency, total)
    print(f"\n===== [{mode}] total={total}, concurrency={concurrency} (sustained) =====")
    print(f"  prompt: {prompt!r}")
    if mode == "edit":
        print(f"  image: {args.image}")

    os.makedirs(args.output_dir, exist_ok=True)
    results = []
    done = 0
    print_lock = threading.Lock()
    t_start = time.time()

    # ThreadPoolExecutor 天然持续并发:worker 空闲立即取下一个任务,无整批等待
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(do_request, mode, i, args, image_bytes, prompt) for i in range(total)]
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            done += 1
            with print_lock:
                if r["ok"]:
                    print(f"  [{done:>3}/{total}] ok    #{r['idx']:>3}  {r['latency']:6.1f}s"
                          f"  (server {r['server_time'] if r['server_time'] is not None else float('nan'):.1f}s)"
                          f"  seed={r['seed']}")
                else:
                    print(f"  [{done:>3}/{total}] FAIL  #{r['idx']:>3}  {r['latency']:6.1f}s"
                          f"  status={r['status']}  {r['error']}")

    wall = time.time() - t_start
    ok_results = [r for r in results if r["ok"]]
    fail_results = [r for r in results if not r["ok"]]
    lat = sorted(r["latency"] for r in results)
    ok_lat = sorted(r["latency"] for r in ok_results)
    server_times = [r["server_time"] for r in ok_results if r["server_time"] is not None]

    print(f"  ----- summary [{mode}] -----")
    print(f"  success: {len(ok_results)}/{total}" + (f" (failed {len(fail_results)})" if fail_results else ""))
    print(f"  wall time: {wall:.1f}s, throughput: {total / wall:.3f} req/s" if wall > 0 else "")
    if lat:
        print(f"  latency(s): min={lat[0]:.1f} avg={sum(lat)/len(lat):.1f}"
              f" p50={percentile(lat, 50):.1f} p95={percentile(lat, 95):.1f} max={lat[-1]:.1f}")
    if ok_lat:
        print(f"  ok-latency(s): min={ok_lat[0]:.1f} avg={sum(ok_lat)/len(ok_lat):.1f}"
              f" p50={percentile(ok_lat, 50):.1f} p95={percentile(ok_lat, 95):.1f} max={ok_lat[-1]:.1f}")
    if server_times:
        avg_gen = sum(server_times) / len(server_times)
        avg_client = sum(ok_lat) / len(ok_lat)
        print(f"  server gen avg: {avg_gen:.1f}s, client avg: {avg_client:.1f}s "
              f"(queue/transfer overhead avg: {avg_client - avg_gen:.1f}s)")
    if fail_results:
        print(f"  sample errors:")
        for r in fail_results[:3]:
            print(f"    #{r['idx']} status={r['status']}: {r['error']}")


def main() -> None:
    args = parse_args()

    if args.concurrency < 1 or args.total < 1:
        raise SystemExit("--concurrency/--total must be >= 1")
    if args.mode == "both" and (args.concurrency > 1 or args.total > 1):
        raise SystemExit("--mode both only supports single request (concurrency=1, total=1)")
    if args.mode == "edit" and not os.path.isfile(args.image):
        raise SystemExit(f"edit input image not found: {args.image}")

    if not health_check(args.server):
        print("server not ready, abort.")
        return

    image_bytes = b""
    if args.mode in ("edit", "both"):
        with open(args.image, "rb") as f:
            image_bytes = f.read()

    if args.mode == "both":
        # 单请求 both:两个接口各跑一条
        args_gen = args
        run_test("generate", args_gen, image_bytes)
        run_test("edit", args, image_bytes)
    else:
        run_test(args.mode, args, image_bytes)

    print("\ndone.")


if __name__ == "__main__":
    main()
