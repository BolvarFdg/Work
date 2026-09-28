"""boogu_server.py 接口测试脚本(单请求).

依赖: pip install requests
用法: python test_boogu_server.py
"""

import os
import time
import requests

# ====================== 配置区 ======================
SERVER = "http://127.0.0.1:8090"

MODE = "both"  # generate | edit | both

# --- 文生图 /v1/images/generations ---
T2I_PROMPT = "A cinematic mountain landscape illuminated by golden light."
T2I_WIDTH = 1024
T2I_HEIGHT = 1024
T2I_SEED = -1            # -1 = 随机
T2I_OUTPUT = "outputs/t2i_test.png"

# --- 图像编辑 /v1/images/edits ---
EDIT_IMAGE_PATH = "input_image_examples/03.jpg"
EDIT_PROMPT = "Replace the background with a beach while preserving the subject."
EDIT_SEED = -1
EDIT_OUTPUT = "outputs/edit_test.png"

TIMEOUT = (5, 600)  # (连接超时, 读取超时)秒;offload 模式生成较慢,读超时给足
# ====================================================


def health_check() -> bool:
    print(f"[health] GET {SERVER}/health ...")
    try:
        resp = requests.get(f"{SERVER}/health", timeout=TIMEOUT)
        resp.raise_for_status()
        print(f"[health] {resp.json()}")
        return True
    except Exception as exc:
        print(f"[health] FAILED: {exc}")
        return False


def save_image(resp: requests.Response, output_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(resp.content)
    seed = resp.headers.get("X-Seed", "?")
    gen_time = resp.headers.get("X-Generation-Time", "?")
    print(f"  saved: {output_path} ({len(resp.content)} bytes)")
    print(f"  server seed={seed}, generation_time={gen_time}")


def test_generation() -> None:
    print(f"\n[t2i] POST {SERVER}/v1/images/generations")
    print(f"  prompt: {T2I_PROMPT!r}, size={T2I_WIDTH}x{T2I_HEIGHT}, seed={T2I_SEED}")
    payload = {
        "prompt": T2I_PROMPT,
        "width": T2I_WIDTH,
        "height": T2I_HEIGHT,
        "seed": T2I_SEED,
        "format": "png",
    }
    t0 = time.time()
    resp = requests.post(f"{SERVER}/v1/images/generations", json=payload, timeout=TIMEOUT)
    elapsed = time.time() - t0

    if resp.status_code != 200:
        print(f"  FAILED [{resp.status_code}]: {resp.text[:500]}")
        return
    print(f"  status 200, e2e latency {elapsed:.2f}s")
    save_image(resp, T2I_OUTPUT)


def test_edit() -> None:
    if not os.path.isfile(EDIT_IMAGE_PATH):
        print(f"\n[edit] SKIP: input image not found: {EDIT_IMAGE_PATH}")
        return

    print(f"\n[edit] POST {SERVER}/v1/images/edits")
    print(f"  image: {EDIT_IMAGE_PATH}")
    print(f"  prompt: {EDIT_PROMPT!r}, seed={EDIT_SEED}")
    with open(EDIT_IMAGE_PATH, "rb") as f:
        files = {"image": (os.path.basename(EDIT_IMAGE_PATH), f, "image/jpeg")}
        data = {
            "prompt": EDIT_PROMPT,
            "width": 1024,
            "height": 1024,
            "seed": str(EDIT_SEED),
            "format": "png",
        }
        t0 = time.time()
        resp = requests.post(f"{SERVER}/v1/images/edits", files=files, data=data, timeout=TIMEOUT)
    elapsed = time.time() - t0

    if resp.status_code != 200:
        print(f"  FAILED [{resp.status_code}]: {resp.text[:500]}")
        return
    print(f"  status 200, e2e latency {elapsed:.2f}s")
    save_image(resp, EDIT_OUTPUT)


def main() -> None:
    if not health_check():
        print("server not ready, abort.")
        return
    if MODE in ("generate", "both"):
        test_generation()
    if MODE in ("edit", "both"):
        test_edit()
    print("\ndone.")


if __name__ == "__main__":
    main()
