"""OpenClaw Images — REST API for AI image generation.

Uses ComfyUI (local RTX 4090) with cloud fallback (fal.ai / RunPod).
"""

from __future__ import annotations

import io
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cloud_router import CloudRouter
from comfyui_client import ComfyUIClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("openclaw-images")

VALID_MODELS = {"flux-dev", "flux-schnell", "sdxl"}


class GenerateRequest(BaseModel):
    prompt: str
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    model: str = "flux-dev"
    steps: int = 20
    guidance_scale: float = 3.5
    seed: int = -1
    negative_prompt: str = ""

comfyui: ComfyUIClient | None = None
router: CloudRouter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global comfyui, router

    comfyui_url = os.environ.get("COMFYUI_URL", "http://localhost:8188")
    max_queue = int(os.environ.get("MAX_QUEUE_DEPTH", "3"))
    fal_key = os.environ.get("FAL_KEY") or None
    runpod_key = os.environ.get("RUNPOD_API_KEY") or None
    runpod_endpoint = os.environ.get("RUNPOD_ENDPOINT_ID") or None

    comfyui = ComfyUIClient(comfyui_url)
    router = CloudRouter(
        comfyui=comfyui,
        max_queue_depth=max_queue,
        fal_key=fal_key,
        runpod_api_key=runpod_key,
        runpod_endpoint_id=runpod_endpoint,
    )

    logger.info("ComfyUI: %s | Cloud: fal=%s runpod=%s", comfyui_url, bool(fal_key), bool(runpod_key))
    yield

    await router.close()
    await comfyui.close()


app = FastAPI(title="OpenClaw Images API", lifespan=lifespan)


# ------------------------------------------------------------------
# GET /health
# ------------------------------------------------------------------

@app.get("/health")
async def health():
    cloud = []
    if router and router.fal_key:
        cloud.append("fal.ai")
    if router and router.runpod_api_key:
        cloud.append("RunPod")

    result = {
        "status": "ok",
        "comfyui_connected": False,
        "gpu": None,
        "vram_free_mb": 0,
        "queue_running": 0,
        "queue_pending": 0,
        "cloud_fallback": cloud,
    }

    try:
        stats = await comfyui.health()
        queue = await comfyui.queue_status()

        result["comfyui_connected"] = True
        result["queue_running"] = len(queue.get("queue_running", []))
        result["queue_pending"] = len(queue.get("queue_pending", []))

        devices = stats.get("devices", [])
        if devices:
            dev = devices[0]
            result["gpu"] = dev.get("name")
            result["vram_free_mb"] = int(dev.get("vram_free", 0) / (1024 * 1024))
    except Exception as e:
        logger.warning("ComfyUI health check failed: %s", e)

    return result


# ------------------------------------------------------------------
# POST /generate
# ------------------------------------------------------------------

@app.post("/generate")
async def generate(req: GenerateRequest):
    if req.model not in VALID_MODELS:
        raise HTTPException(400, f"model must be one of {VALID_MODELS}")

    try:
        image_bytes, metadata = await router.generate(
            prompt=req.prompt,
            width=req.width,
            height=req.height,
            model=req.model,
            steps=req.steps,
            guidance_scale=req.guidance_scale,
            seed=req.seed,
            negative_prompt=req.negative_prompt,
        )
    except Exception as e:
        logger.error("Generation failed: %s", e)
        raise HTTPException(503, detail=str(e))

    actual_seed = metadata.get("seed", req.seed)
    source = metadata.get("source", "unknown")

    return StreamingResponse(
        io.BytesIO(image_bytes),
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="openclaw_{actual_seed}.png"',
            "X-Source": source,
            "X-Seed": str(actual_seed),
            "X-Model": req.model,
        },
    )


# ------------------------------------------------------------------
# POST /generate/img2img
# ------------------------------------------------------------------

@app.post("/generate/img2img")
async def generate_img2img(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    width: int = Form(1024),
    height: int = Form(1024),
    model: str = Form("flux-dev"),
    steps: int = Form(20),
    guidance_scale: float = Form(3.5),
    seed: int = Form(-1),
    denoise: float = Form(0.65),
):
    if model not in VALID_MODELS:
        raise HTTPException(400, f"model must be one of {VALID_MODELS}")
    if denoise < 0.0 or denoise > 1.0:
        raise HTTPException(400, "denoise must be between 0.0 and 1.0")

    image_bytes = await image.read()
    try:
        upload_result = await comfyui.upload_image(image_bytes, "input.png")
        input_image_name = upload_result.get("name", "input.png")
    except Exception as e:
        raise HTTPException(503, detail=f"Failed to upload image to ComfyUI: {e}")

    try:
        result_bytes, metadata = await router.generate(
            prompt=prompt,
            width=width,
            height=height,
            model=model,
            steps=steps,
            guidance_scale=guidance_scale,
            seed=seed,
            input_image=input_image_name,
            denoise=denoise,
        )
    except Exception as e:
        logger.error("img2img generation failed: %s", e)
        raise HTTPException(503, detail=str(e))

    actual_seed = metadata.get("seed", seed)
    source = metadata.get("source", "unknown")

    return StreamingResponse(
        io.BytesIO(result_bytes),
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="openclaw_{actual_seed}.png"',
            "X-Source": source,
            "X-Seed": str(actual_seed),
            "X-Model": model,
        },
    )


# ------------------------------------------------------------------
# GET /models
# ------------------------------------------------------------------

@app.get("/models")
async def models():
    try:
        checkpoints = await comfyui.list_models("checkpoints")
        loras = await comfyui.list_models("loras")
        return {"checkpoints": checkpoints, "loras": loras}
    except Exception as e:
        raise HTTPException(503, detail=f"ComfyUI unavailable: {e}")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000)
