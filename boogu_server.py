"""Boogu-Image-0.1-Edit-Turbo Ascend NPU 推理服务.

用法:
    pip install fastapi uvicorn python-multipart
    python boogu_server.py            # 在 Boogu-Image 目录下启动

接口:
    GET  /health                      健康检查
    POST /v1/images/generations       文生图(JSON)
    POST /v1/images/edits             图像编辑(multipart 上传图片)

示例:
    # 文生图
    curl -X POST http://127.0.0.1:8090/v1/images/generations \
        -H "Content-Type: application/json" \
        -d '{"prompt": "A cinematic mountain landscape."}' \
        --output out.png

    # 图像编辑
    curl -X POST http://127.0.0.1:8090/v1/images/edits \
        -F "image=@input.jpg" \
        -F "prompt=把背景替换到沙滩" \
        --output edited.png
"""

import os
import sys
import io
import time
import base64
import random
import tempfile
import threading

# ====================== 配置区 ======================
HOST = "0.0.0.0"
PORT = 8090

MODEL_PATH = "models/Boogu-Image-0.1-Edit-Turbo"  # 模型目录(相对本文件或绝对路径)
NPU_CARD = 0               # 物理卡号,对应 ASCEND_RT_VISIBLE_DEVICES
DEVICE = "npu:0"           # 进程内逻辑设备
ENABLE_CPU_OFFLOAD = True  # 32GB 卡必须 True;64GB 卡可 False(更快)

NUM_STEPS = 4              # Edit-Turbo DMD 步数
DMD_SIGMA = 0.0            # Edit-Turbo 用 0.0;换纯文生图 Turbo 则改 0.001
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
# ====================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["ASCEND_RT_VISIBLE_DEVICES"] = str(NPU_CARD)
os.environ["device"] = DEVICE
os.environ.setdefault("HF_MODULES_CACHE", os.path.join(BASE_DIR, ".hf_modules_cache"))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import torch
import torch_npu  # noqa: F401  必须在 torch 之后导入
from fastapi import FastAPI, File, Form, HTTPException
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from boogu.pipelines.boogu.pipeline_boogu_turbo import BooguImageTurboPipeline

app = FastAPI(title="Boogu-Image Edit-Turbo NPU Server")
_lock = threading.Lock()
_pipeline = None


def load_pipeline() -> BooguImageTurboPipeline:
    model_path = MODEL_PATH if os.path.isabs(MODEL_PATH) else os.path.join(BASE_DIR, MODEL_PATH)
    if not os.path.isfile(os.path.join(model_path, "model_index.json")):
        raise FileNotFoundError(f"model_index.json not found under {model_path}")

    torch.npu.set_device(DEVICE)
    print(f"[Server] Loading pipeline: {model_path} on {DEVICE} (offload={ENABLE_CPU_OFFLOAD})")
    pipe = BooguImageTurboPipeline.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    if ENABLE_CPU_OFFLOAD:
        pipe.enable_model_cpu_offload(device=DEVICE)
    else:
        pipe.to(DEVICE)
    return pipe


def run_generation(prompt: str, input_image: Image.Image, input_image_path, width: int, height: int, seed: int):
    if seed is None or seed < 0:
        seed = random.randint(0, 2**31 - 1)
    generator = torch.Generator(device=DEVICE).manual_seed(seed)

    kwargs = dict(
        instruction=[prompt],
        negative_instruction="",
        empty_instruction="",
        width=width,
        height=height,
        max_input_image_pixels=width * height,
        max_input_image_side_length=2 * max(width, height),
        num_inference_steps=NUM_STEPS,
        text_guidance_scale=1.0,
        image_guidance_scale=1.0,
        empty_instruction_guidance_scale=0.0,
        generator=generator,
        output_type="pil",
        device=DEVICE,
        use_dmd_student_inference=True,
        dmd_conditioning_sigma=DMD_SIGMA,
    )
    if input_image is not None:
        kwargs["input_images"] = [[input_image]]
        if input_image_path:
            kwargs["input_image_paths"] = [[input_image_path]]

    try:
        with torch.inference_mode():
            result = _pipeline(**kwargs)
        return result.images[0], seed
    finally:
        torch.npu.empty_cache()


def image_response(image: Image.Image, seed: int, elapsed: float, fmt: str) -> Response:
    buf = io.BytesIO()
    if fmt == "jpeg":
        image.save(buf, format="JPEG", quality=95)
        media = "image/jpeg"
    else:
        image.save(buf, format="PNG")
        media = "image/png"
    return Response(
        content=buf.getvalue(),
        media_type=media,
        headers={"X-Seed": str(seed), "X-Generation-Time": f"{elapsed:.2f}s"},
    )


@app.on_event("startup")
def startup():
    global _pipeline
    _pipeline = load_pipeline()
    print(f"[Server] Ready at http://{HOST}:{PORT}")


@app.get("/health")
def health():
    return {
        "status": "ok" if _pipeline is not None else "loading",
        "model": MODEL_PATH,
        "device": DEVICE,
        "offload": ENABLE_CPU_OFFLOAD,
    }


class GenerateRequest(BaseModel):
    prompt: str
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    seed: int = -1
    format: str = "png"  # png | jpeg


@app.post("/v1/images/generations")
def text_to_image(req: GenerateRequest):
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="pipeline not ready")
    with _lock:
        t0 = time.time()
        try:
            image, seed = run_generation(req.prompt, None, None, req.width, req.height, req.seed)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"generation failed: {exc}")
        return image_response(image, seed, time.time() - t0, req.format)


@app.post("/v1/images/edits")
def image_edit(
    image: bytes = File(..., description="输入图片"),
    prompt: str = Form(...),
    width: int = Form(DEFAULT_WIDTH),
    height: int = Form(DEFAULT_HEIGHT),
    seed: int = Form(-1),
    format: str = Form("png"),
):
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="pipeline not ready")
    try:
        pil_image = Image.open(io.BytesIO(image)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid image file")

    # 与官方入口保持一致:同时传 input_images 和 input_image_paths
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    pil_image.save(tmp, format="PNG")
    tmp.close()

    with _lock:
        t0 = time.time()
        try:
            result, seed = run_generation(prompt, pil_image, tmp.name, width, height, seed)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"generation failed: {exc}")
        finally:
            os.unlink(tmp.name)
        return image_response(result, seed, time.time() - t0, format)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, workers=1)
