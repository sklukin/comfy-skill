"""Health-check-based routing: local ComfyUI → cloud fallback (fal.ai / RunPod)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

from comfyui_client import ComfyUIClient

logger = logging.getLogger(__name__)


class CloudRouter:
    def __init__(
        self,
        comfyui: ComfyUIClient,
        max_queue_depth: int = 3,
        fal_key: str | None = None,
        runpod_api_key: str | None = None,
        runpod_endpoint_id: str | None = None,
        gpu_paused_check: Callable[[], bool] | None = None,
    ):
        self.comfyui = comfyui
        self.max_queue_depth = max_queue_depth
        self.fal_key = fal_key
        self.runpod_api_key = runpod_api_key
        self.runpod_endpoint_id = runpod_endpoint_id
        self._gpu_paused_check = gpu_paused_check
        self._http = httpx.AsyncClient(timeout=120.0)

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def is_local_healthy(self) -> bool:
        """Check if ComfyUI is reachable, queue not saturated, GPU has free VRAM."""
        if self._gpu_paused_check and self._gpu_paused_check():
            logger.info("GPU paused (gaming mode), local unavailable")
            return False
        try:
            stats = await self.comfyui.health()
            queue = await self.comfyui.queue_status()

            # Queue depth check
            running = len(queue.get("queue_running", []))
            pending = len(queue.get("queue_pending", []))
            if running + pending >= self.max_queue_depth:
                logger.info("ComfyUI queue full: %d running + %d pending >= %d", running, pending, self.max_queue_depth)
                return False

            # VRAM check (if available)
            devices = stats.get("devices", [])
            if devices:
                dev = devices[0]
                vram_free = dev.get("vram_free", 0)
                # Need at least 2GB free for model loading overhead
                if vram_free > 0 and vram_free < 2 * 1024 * 1024 * 1024:
                    logger.info("ComfyUI low VRAM: %dMB free", vram_free // (1024 * 1024))
                    return False

            return True
        except Exception as e:
            logger.warning("ComfyUI health check failed: %s", e)
            return False

    async def should_use_cloud(self) -> bool:
        """Returns True if we should route to cloud instead of local."""
        if not await self.is_local_healthy():
            if self.fal_key or self.runpod_api_key:
                return True
            logger.warning("Local unhealthy but no cloud keys configured")
        return False

    # ------------------------------------------------------------------
    # Cloud providers
    # ------------------------------------------------------------------

    async def generate_fal(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        guidance_scale: float = 3.5,
        seed: int = -1,
    ) -> tuple[bytes, str]:
        """Generate via fal.ai FLUX API. Returns (image_bytes, image_url)."""
        if not self.fal_key:
            raise RuntimeError("FAL_KEY not configured")

        payload: dict[str, Any] = {
            "prompt": prompt,
            "image_size": {"width": width, "height": height},
            "num_inference_steps": steps,
            "guidance_scale": guidance_scale,
            "num_images": 1,
            "output_format": "png",
            "enable_safety_checker": True,
        }
        if seed >= 0:
            payload["seed"] = seed

        r = await self._http.post(
            "https://fal.run/fal-ai/flux/dev",
            headers={
                "Authorization": f"Key {self.fal_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()

        image_url = data["images"][0]["url"]
        image_r = await self._http.get(image_url, timeout=30.0)
        image_r.raise_for_status()

        return image_r.content, image_url

    async def generate_runpod(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        guidance_scale: float = 3.5,
        seed: int = -1,
    ) -> tuple[bytes, str]:
        """Generate via RunPod serverless endpoint. Returns (image_bytes, job_id)."""
        if not self.runpod_api_key or not self.runpod_endpoint_id:
            raise RuntimeError("RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID required")

        import asyncio
        import base64

        payload = {
            "input": {
                "prompt": prompt,
                "width": width,
                "height": height,
                "steps": steps,
                "guidance_scale": guidance_scale,
                "seed": seed if seed >= 0 else None,
            }
        }

        # Submit job
        r = await self._http.post(
            f"https://api.runpod.ai/v2/{self.runpod_endpoint_id}/runsync",
            headers={"Authorization": f"Bearer {self.runpod_api_key}"},
            json=payload,
            timeout=120.0,
        )
        r.raise_for_status()
        result = r.json()

        # runsync returns result directly if fast enough
        if result.get("status") == "COMPLETED":
            output = result["output"]
        else:
            # Poll for completion
            job_id = result["id"]
            for _ in range(60):
                await asyncio.sleep(2.0)
                r = await self._http.get(
                    f"https://api.runpod.ai/v2/{self.runpod_endpoint_id}/status/{job_id}",
                    headers={"Authorization": f"Bearer {self.runpod_api_key}"},
                )
                r.raise_for_status()
                result = r.json()
                if result["status"] == "COMPLETED":
                    output = result["output"]
                    break
                if result["status"] in ("FAILED", "CANCELLED"):
                    raise RuntimeError(f"RunPod job {result['status']}: {result.get('error')}")
            else:
                raise TimeoutError("RunPod job timed out")

        # Output is typically base64-encoded image
        image_b64 = output.get("image") or output.get("images", [None])[0]
        if not image_b64:
            raise RuntimeError("No image in RunPod response")
        image_bytes = base64.b64decode(image_b64)

        return image_bytes, result.get("id", "runpod")

    # ------------------------------------------------------------------
    # Smart routing
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        model: str = "flux-dev",
        steps: int = 20,
        guidance_scale: float = 3.5,
        seed: int = -1,
        input_image: str | None = None,
        mask_image: str | None = None,
        denoise: float | None = None,
        negative_prompt: str = "",
    ) -> tuple[bytes, dict]:
        """Generate image with automatic local/cloud routing.

        Returns (image_bytes, metadata) where metadata includes 'source'.
        """
        use_cloud = await self.should_use_cloud()

        if not use_cloud:
            try:
                params = {
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "seed": seed,
                    "steps": steps,
                    "guidance_scale": guidance_scale,
                    "negative_prompt": negative_prompt,
                }
                if input_image:
                    params["input_image"] = input_image
                if mask_image:
                    params["mask_image"] = mask_image

                # Determine internal model name
                if model in ("flux-fill", "flux-canny", "flux-depth", "flux-kontext"):
                    actual_model = model
                elif input_image and model == "flux-dev":
                    actual_model = "flux-dev-img2img"
                else:
                    actual_model = model

                if denoise is not None:
                    params["denoise"] = denoise

                image_bytes, metadata = await self.comfyui.generate(actual_model, params)
                metadata["source"] = "local"
                return image_bytes, metadata
            except Exception as e:
                logger.warning("Local generation failed, trying cloud: %s", e)
                if not (self.fal_key or self.runpod_api_key):
                    raise

        # Cloud fallback
        source = "unknown"
        if self.fal_key:
            image_bytes, url = await self.generate_fal(
                prompt, width, height, steps, guidance_scale, seed
            )
            source = "fal.ai"
            metadata = {"source": source, "url": url, "model": model}
        elif self.runpod_api_key:
            image_bytes, job_id = await self.generate_runpod(
                prompt, width, height, steps, guidance_scale, seed
            )
            source = "runpod"
            metadata = {"source": source, "job_id": job_id, "model": model}
        else:
            raise RuntimeError("No cloud provider configured and local ComfyUI unavailable")

        return image_bytes, metadata

    async def close(self):
        await self._http.aclose()
