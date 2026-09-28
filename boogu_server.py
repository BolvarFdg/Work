"""Boogu-Image Ascend NPU 推理服务(支持 Turbo/标准双模式 + DiT 替换).

用法:
    pip install fastapi uvicorn python-multipart
    python boogu_server.py                       # 全部用默认参数
    python boogu_server.py --help                # 查看全部参数
    python boogu_server.py --port 8091 --npu-card 2 --cpu-offload false
    python boogu_server.py --use-custom-dit true --custom-dit-path /data/dits/my_variant

    改默认值:直接改 parse_args() 里各参数的 default= 值。

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

import argparse
import os
import sys
import io
import time
import random
import tempfile
import threading


def _str2bool(value) -> bool:
    if isinstance(value, bool):
        return value
    value = str(value).strip().lower()
    if value in {"true", "t", "1", "yes", "y", "on"}:
        return True
    if value in {"false", "f", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid bool value: {value!r} (true/false/1/0)")


def parse_args() -> argparse.Namespace:
    """所有服务参数;想改默认值就改这里的 default=。"""
    parser = argparse.ArgumentParser(description="Boogu-Image Ascend NPU server")

    # --- 服务 ---
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8090, help="监听端口")
    parser.add_argument("--log-level", type=str, default="INFO", help="DEBUG/INFO/WARNING/ERROR")

    # --- 模型与设备 ---
    parser.add_argument(
        "--model-path", type=str, default="models/Boogu-Image-0.1-Edit-Turbo",
        help="模型目录(相对本文件或绝对路径)",
    )
    parser.add_argument("--npu-card", type=int, default=0, help="物理卡号,对应 ASCEND_RT_VISIBLE_DEVICES")
    parser.add_argument("--device", type=str, default="npu:0", help="进程内逻辑设备")
    parser.add_argument(
        "--cpu-offload", type=_str2bool, default=True,
        help="CPU offload;32GB 卡必须 true,64GB 卡可 false(更快)",
    )

    # --- Turbo 开关(启动时确定) ---
    parser.add_argument(
        "--use-turbo", type=_str2bool, default=True,
        help="true: BooguImageTurboPipeline(4步DMD,配 Turbo/Edit-Turbo 权重);"
             "false: BooguImagePipeline(50步标准,配 Base/Edit 权重)",
    )

    # --- 替换 DiT(启动时确定) ---
    parser.add_argument(
        "--use-custom-dit", type=_str2bool, default=False,
        help="是否用替换 DiT 启动",
    )
    parser.add_argument(
        "--custom-dit-path", type=str, default="",
        help="替换 DiT 目录,须为 BooguImageTransformer2DModel 同构权重",
    )

    # --- 生成参数 ---
    parser.add_argument(
        "--num-steps", type=int, default=None,
        help="去噪步数;不传则按 use-turbo 自动取 4 或 50",
    )
    parser.add_argument(
        "--text-guidance-scale", type=float, default=None,
        help="文本引导;不传则按 use-turbo 自动取 1.0 或 4.0",
    )
    parser.add_argument(
        "--dmd-sigma", type=float, default=0.0,
        help="仅 use-turbo=true 生效:Edit-Turbo=0.0,纯文生图 Turbo=0.001",
    )
    parser.add_argument("--width", type=int, default=1024, help="默认输出宽度")
    parser.add_argument("--height", type=int, default=1024, help="默认输出高度")

    return parser.parse_args()


ARGS = parse_args()
NUM_STEPS = ARGS.num_steps if ARGS.num_steps is not None else (4 if ARGS.use_turbo else 50)
TEXT_GUIDANCE_SCALE = (
    ARGS.text_guidance_scale if ARGS.text_guidance_scale is not None
    else (1.0 if ARGS.use_turbo else 4.0)
)

# ---- 环境变量必须在 import torch_npu / boogu 之前设置 ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["ASCEND_RT_VISIBLE_DEVICES"] = str(ARGS.npu_card)
os.environ["device"] = ARGS.device
os.environ.setdefault("HF_MODULES_CACHE", os.path.join(BASE_DIR, ".hf_modules_cache"))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import logging

logging.basicConfig(
    level=getattr(logging, ARGS.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("boogu_server")

import torch
import torch_npu  # noqa: F401  必须在 torch 之后导入
from fastapi import FastAPI, File, Form, HTTPException
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from boogu.pipelines.boogu.pipeline_boogu import BooguImagePipeline
from boogu.pipelines.boogu.pipeline_boogu_turbo import BooguImageTurboPipeline
from boogu.models.transformers.transformer_boogu import BooguImageTransformer2DModel

app = FastAPI(title="Boogu-Image NPU Server")
_lock = threading.Lock()
_pipeline = None


def load_pipeline():
    model_path = (
        ARGS.model_path if os.path.isabs(ARGS.model_path)
        else os.path.join(BASE_DIR, ARGS.model_path)
    )
    if not os.path.isfile(os.path.join(model_path, "model_index.json")):
        raise FileNotFoundError(f"model_index.json not found under {model_path}")

    torch.npu.set_device(ARGS.device)
    pipeline_class = BooguImageTurboPipeline if ARGS.use_turbo else BooguImagePipeline
    logger.info(
        "Loading %s (turbo=%s, steps=%d, text_cfg=%.1f) from %s on %s (cpu_offload=%s)",
        pipeline_class.__name__, ARGS.use_turbo, NUM_STEPS, TEXT_GUIDANCE_SCALE,
        model_path, ARGS.device, ARGS.cpu_offload,
    )
    pipe = pipeline_class.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )

    # 替换 DiT:必须在 enable offload / .to 之前完成,
    # 这样 offload 钩子会挂到替换后的 transformer 上(与 inference_turbo.py 顺序一致)
    if ARGS.use_custom_dit:
        dit_path = (
            ARGS.custom_dit_path if os.path.isabs(ARGS.custom_dit_path)
            else os.path.join(BASE_DIR, ARGS.custom_dit_path)
        )
        if not os.path.isfile(os.path.join(dit_path, "config.json")):
            raise FileNotFoundError(
                f"--custom-dit-path invalid, config.json not found: {dit_path} "
                "(must be a BooguImageTransformer2DModel-compatible checkpoint)"
            )
        logger.info("Replacing diffusion transformer with: %s", dit_path)
        transformer = BooguImageTransformer2DModel.from_pretrained(
            dit_path,
            torch_dtype=torch.bfloat16,
        )
        pipe.set_transformer(transformer)

    if ARGS.cpu_offload:
        pipe.enable_model_cpu_offload(device=ARGS.device)
    else:
        pipe.to(ARGS.device)
    return pipe


def run_generation(prompt: str, input_image: Image.Image, input_image_path, width: int, height: int, seed: int):
    if seed is None or seed < 0:
        seed = random.randint(0, 2**31 - 1)
    generator = torch.Generator(device=ARGS.device).manual_seed(seed)

    kwargs = dict(
        instruction=[prompt],
        negative_instruction="",
        empty_instruction="",
        width=width,
        height=height,
        max_input_image_pixels=width * height,
        max_input_image_side_length=2 * max(width, height),
        num_inference_steps=NUM_STEPS,
        text_guidance_scale=TEXT_GUIDANCE_SCALE,
        image_guidance_scale=1.0,
        empty_instruction_guidance_scale=0.0,
        generator=generator,
        output_type="pil",
        device=ARGS.device,
    )
    if ARGS.use_turbo:
        kwargs["use_dmd_student_inference"] = True
        kwargs["dmd_conditioning_sigma"] = ARGS.dmd_sigma
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
    logger.info("Server ready at http://%s:%s", ARGS.host, ARGS.port)


@app.get("/health")
def health():
    return {
        "status": "ok" if _pipeline is not None else "loading",
        "model": ARGS.model_path,
        "turbo": ARGS.use_turbo,
        "steps": NUM_STEPS,
        "device": ARGS.device,
        "offload": ARGS.cpu_offload,
        "custom_dit": ARGS.custom_dit_path if ARGS.use_custom_dit else None,
    }


class GenerateRequest(BaseModel):
    prompt: str
    width: int = ARGS.width
    height: int = ARGS.height
    seed: int = -1
    format: str = "png"  # png | jpeg


@app.post("/v1/images/generations")
def text_to_image(req: GenerateRequest):
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="pipeline not ready")
    logger.info("T2I request: prompt=%r, size=%dx%d, seed=%d", req.prompt, req.width, req.height, req.seed)
    with _lock:
        t0 = time.time()
        try:
            image, seed = run_generation(req.prompt, None, None, req.width, req.height, req.seed)
        except Exception as exc:
            logger.exception("T2I generation failed")
            raise HTTPException(status_code=500, detail=f"generation failed: {exc}")
        elapsed = time.time() - t0
        logger.info("T2I done: seed=%d, elapsed=%.2fs", seed, elapsed)
        return image_response(image, seed, elapsed, req.format)


@app.post("/v1/images/edits")
def image_edit(
    image: bytes = File(..., description="输入图片"),
    prompt: str = Form(...),
    width: int = Form(ARGS.width),
    height: int = Form(ARGS.height),
    seed: int = Form(-1),
    format: str = Form("png"),
):
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="pipeline not ready")
    try:
        pil_image = Image.open(io.BytesIO(image)).convert("RGB")
    except Exception:
        logger.warning("Edit request rejected: invalid image file")
        raise HTTPException(status_code=400, detail="invalid image file")

    # 与官方入口保持一致:同时传 input_images 和 input_image_paths
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    pil_image.save(tmp, format="PNG")
    tmp.close()

    logger.info(
        "Edit request: prompt=%r, input=%dx%d, output=%dx%d, seed=%d",
        prompt, pil_image.width, pil_image.height, width, height, seed,
    )
    with _lock:
        t0 = time.time()
        try:
            result, seed = run_generation(prompt, pil_image, tmp.name, width, height, seed)
        except Exception as exc:
            logger.exception("Edit generation failed")
            raise HTTPException(status_code=500, detail=f"generation failed: {exc}")
        finally:
            os.unlink(tmp.name)
        elapsed = time.time() - t0
        logger.info("Edit done: seed=%d, elapsed=%.2fs", seed, elapsed)
        return image_response(result, seed, elapsed, format)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=ARGS.host, port=ARGS.port, workers=1)
