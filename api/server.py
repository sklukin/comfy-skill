"""OpenClaw Images — REST API for AI image generation.

Uses ComfyUI (local RTX 4090) with cloud fallback (fal.ai / RunPod).
All generation goes through an async job queue.
"""

from __future__ import annotations

import io
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from cloud_router import CloudRouter
from comfyui_client import ComfyUIClient
from queue_manager import JobQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("openclaw-images")

VALID_MODELS = {"flux-dev", "flux-schnell", "flux-fill", "flux-canny", "flux-depth", "flux-kontext", "sdxl", "upscale", "wan-video"}

comfyui: ComfyUIClient | None = None
router: CloudRouter | None = None
job_queue: JobQueue | None = None


class JobRequest(BaseModel):
    prompt: str = ""
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    model: str = "flux-dev"
    steps: int = 20
    guidance_scale: float = 3.5
    seed: int = -1
    negative_prompt: str = ""
    input_image: str | None = None
    mask_image: str | None = None
    denoise: float | None = Field(default=None, ge=0.0, le=1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global comfyui, router, job_queue

    comfyui_url = os.environ.get("COMFYUI_URL", "http://localhost:8188")
    max_queue = int(os.environ.get("MAX_QUEUE_DEPTH", "3"))
    fal_key = os.environ.get("FAL_KEY") or None
    runpod_key = os.environ.get("RUNPOD_API_KEY") or None
    runpod_endpoint = os.environ.get("RUNPOD_ENDPOINT_ID") or None
    max_jobs = int(os.environ.get("MAX_QUEUE_JOBS", "50"))
    result_ttl = float(os.environ.get("JOB_RESULT_TTL", "600"))

    comfyui = ComfyUIClient(comfyui_url)
    router = CloudRouter(
        comfyui=comfyui,
        max_queue_depth=max_queue,
        fal_key=fal_key,
        runpod_api_key=runpod_key,
        runpod_endpoint_id=runpod_endpoint,
    )

    idle_timeout = float(os.environ.get("IDLE_VRAM_FREE_TIMEOUT", "300"))
    job_queue = JobQueue(
        router=router, comfyui=comfyui, max_jobs=max_jobs,
        result_ttl=result_ttl, idle_vram_timeout=idle_timeout,
    )
    router._gpu_paused_check = lambda: job_queue.gpu_paused
    await job_queue.start()

    logger.info("ComfyUI: %s | Cloud: fal=%s runpod=%s", comfyui_url, bool(fal_key), bool(runpod_key))
    yield

    await job_queue.stop()
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
        "gpu_paused": job_queue.gpu_paused if job_queue else False,
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
# POST /jobs — submit a generation job
# ------------------------------------------------------------------

@app.post("/jobs")
async def submit_job(req: JobRequest):
    if req.model not in VALID_MODELS:
        raise HTTPException(400, f"model must be one of {VALID_MODELS}")
    if req.model == "flux-fill" and not req.input_image:
        raise HTTPException(400, "flux-fill requires input_image (upload image first via /upload)")
    if req.model == "flux-fill" and not req.mask_image:
        raise HTTPException(400, "flux-fill requires mask_image (upload mask first via /upload)")
    if req.model in ("flux-canny", "flux-depth", "flux-kontext") and not req.input_image:
        raise HTTPException(400, f"{req.model} requires input_image (upload image first via /upload)")
    if req.model == "upscale" and not req.input_image:
        raise HTTPException(400, "upscale requires input_image (upload image first via /upload)")
    if req.model == "wan-video" and not req.input_image:
        raise HTTPException(400, "wan-video requires input_image (upload image first via /upload)")
    if req.input_image and req.denoise is None and req.model not in ("upscale", "wan-video"):
        req.denoise = 0.65

    cloud_available = bool(router and (router.fal_key or router.runpod_api_key))

    if job_queue and job_queue.gpu_paused and not cloud_available:
        raise HTTPException(503, "GPU paused (gaming mode), no cloud fallback configured")

    try:
        await comfyui.health()
    except Exception:
        if not cloud_available:
            raise HTTPException(503, "ComfyUI unavailable, no cloud fallback configured")

    request_params = {
        "prompt": req.prompt,
        "width": req.width,
        "height": req.height,
        "model": req.model,
        "steps": req.steps,
        "guidance_scale": req.guidance_scale,
        "seed": req.seed,
        "negative_prompt": req.negative_prompt,
    }
    if req.input_image:
        request_params["input_image"] = req.input_image
    if req.mask_image:
        request_params["mask_image"] = req.mask_image
    if req.denoise is not None:
        request_params["denoise"] = req.denoise

    try:
        job = job_queue.submit(request_params)
    except RuntimeError as e:
        raise HTTPException(429, detail=str(e))

    return {
        "job_id": job.id,
        "status": job.status,
        "position": job_queue.get_position(job.id),
        "created_at": job.created_at,
    }


# ------------------------------------------------------------------
# GET /jobs/{job_id} — check job status
# ------------------------------------------------------------------

@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    resp = {
        "job_id": job.id,
        "status": job.status,
        "position": job_queue.get_position(job.id),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error": job.error,
    }
    if job.result_metadata:
        resp["source"] = job.result_metadata.get("source")
        resp["seed"] = job.result_metadata.get("seed")
    return resp


# ------------------------------------------------------------------
# GET /jobs/{job_id}/result — download generated image
# ------------------------------------------------------------------

@app.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str):
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status in ("queued", "processing"):
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job.id,
                "status": job.status,
                "position": job_queue.get_position(job.id),
            },
        )

    if job.status == "failed":
        raise HTTPException(410, detail=f"Job failed: {job.error}")

    if job.status == "cancelled":
        raise HTTPException(410, detail="Job was cancelled")

    if not job.result:
        raise HTTPException(410, detail="Result expired")

    metadata = job.result_metadata or {}
    filename_ext = metadata.get("filename", "")
    if filename_ext.endswith(".webp"):
        media_type = "image/webp"
        out_filename = f"openclaw_{job.id[:8]}.webp"
    else:
        media_type = "image/png"
        out_filename = f"openclaw_{job.id[:8]}.png"
    return StreamingResponse(
        io.BytesIO(job.result),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{out_filename}"',
            "X-Source": metadata.get("source", "unknown"),
            "X-Seed": str(metadata.get("seed", -1)),
            "X-Model": metadata.get("model", "unknown"),
        },
    )


# ------------------------------------------------------------------
# DELETE /jobs/{job_id} — cancel a queued job
# ------------------------------------------------------------------

@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "queued":
        raise HTTPException(409, f"Cannot cancel job in '{job.status}' state")
    job_queue.cancel_job(job_id)
    return {"job_id": job_id, "status": "cancelled"}


# ------------------------------------------------------------------
# POST /upload — upload image for img2img
# ------------------------------------------------------------------

@app.post("/upload")
async def upload_image(image: UploadFile = File(...)):
    image_bytes = await image.read()
    try:
        result = await comfyui.upload_image(image_bytes, image.filename or "input.png")
        return {"filename": result.get("name", "input.png")}
    except Exception as e:
        raise HTTPException(503, detail=f"Failed to upload image to ComfyUI: {e}")


# ------------------------------------------------------------------
# POST /gpu/pause — gaming mode ON
# ------------------------------------------------------------------

@app.post("/gpu/pause")
async def gpu_pause():
    job_queue.set_gpu_paused(True)
    freed = await job_queue.free_vram()
    qi = job_queue.queue_info()
    return {
        "gpu_paused": True,
        "vram_freed": freed,
        "message": "GPU на паузе. VRAM освобождён." if freed else "GPU на паузе. Задачи в очереди будут ждать.",
        "queued_jobs": qi["total_queued"],
    }


# ------------------------------------------------------------------
# POST /gpu/resume — gaming mode OFF
# ------------------------------------------------------------------

@app.post("/gpu/resume")
async def gpu_resume():
    job_queue.set_gpu_paused(False)
    qi = job_queue.queue_info()
    return {
        "gpu_paused": False,
        "message": "GPU возобновлён. Обработка очереди продолжается.",
        "queued_jobs": qi["total_queued"],
    }


# ------------------------------------------------------------------
# GET /models
# ------------------------------------------------------------------

@app.get("/models")
async def models():
    try:
        result = {}
        for folder in ("checkpoints", "diffusion_models", "loras", "upscale_models", "controlnet", "style_models"):
            try:
                result[folder] = await comfyui.list_models(folder)
            except Exception:
                result[folder] = []
        return result
    except Exception as e:
        raise HTTPException(503, detail=f"ComfyUI unavailable: {e}")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000)
