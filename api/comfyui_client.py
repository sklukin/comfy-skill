"""Async HTTP/WebSocket client for ComfyUI API."""

from __future__ import annotations

import asyncio
import copy
import json
import random
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import websockets


WORKFLOWS_DIR = Path(__file__).parent / "workflows"

WORKFLOW_MAP = {
    "flux-dev": "flux_dev_txt2img.json",
    "flux-schnell": "flux_schnell_txt2img.json",
    "flux-dev-img2img": "flux_dev_img2img.json",
    "sdxl": "sdxl_txt2img.json",
}


class ComfyUIClient:
    def __init__(self, base_url: str = "http://localhost:8188"):
        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=300.0)

    # ------------------------------------------------------------------
    # Health & status
    # ------------------------------------------------------------------

    async def health(self) -> dict:
        """GET /system_stats — GPU info, VRAM usage, queue."""
        r = await self._http.get("/system_stats", timeout=5.0)
        r.raise_for_status()
        return r.json()

    async def queue_status(self) -> dict:
        """GET /queue — running and pending items."""
        r = await self._http.get("/queue", timeout=5.0)
        r.raise_for_status()
        return r.json()

    async def free_memory(self, unload_models: bool = True, free_mem: bool = True) -> bool:
        """POST /free — unload models and free VRAM."""
        try:
            r = await self._http.post("/free", json={
                "unload_models": unload_models,
                "free_memory": free_mem,
            }, timeout=10.0)
            r.raise_for_status()
            return True
        except Exception:
            return False

    async def list_models(self, folder: str = "checkpoints") -> list[str]:
        """GET /models/{folder} — available model files."""
        r = await self._http.get(f"/models/{folder}", timeout=10.0)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Workflow submission
    # ------------------------------------------------------------------

    async def submit_prompt(self, workflow: dict, client_id: str) -> str:
        """POST /prompt — submit workflow, return prompt_id."""
        payload = {"prompt": workflow, "client_id": client_id}
        r = await self._http.post("/prompt", json=payload)
        r.raise_for_status()
        return r.json()["prompt_id"]

    async def wait_for_completion(self, prompt_id: str, client_id: str, timeout: float = 300.0) -> dict:
        """Monitor WebSocket for prompt completion, fall back to polling."""
        try:
            return await self._wait_ws(prompt_id, client_id, timeout)
        except Exception:
            return await self._poll_history(prompt_id, timeout)

    async def _wait_ws(self, prompt_id: str, client_id: str, timeout: float) -> dict:
        """Connect to /ws and wait for execution to finish for our prompt."""
        uri = f"{self.ws_url}/ws?clientId={client_id}"
        async with websockets.connect(uri, close_timeout=5) as ws:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    remaining = deadline - time.monotonic()
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(30, remaining))
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw) if isinstance(raw, str) else None
                if msg is None:
                    continue
                if msg.get("type") == "executing" and msg.get("data", {}).get("prompt_id") == prompt_id:
                    if msg["data"].get("node") is None:
                        return await self._get_history(prompt_id)
        raise TimeoutError(f"Prompt {prompt_id} did not complete within {timeout}s")

    async def _poll_history(self, prompt_id: str, timeout: float) -> dict:
        """Fallback: poll GET /history/{prompt_id} until outputs appear."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = await self._get_history(prompt_id)
            if history.get("outputs"):
                return history
            await asyncio.sleep(2.0)
        raise TimeoutError(f"Prompt {prompt_id} did not complete within {timeout}s")

    async def _get_history(self, prompt_id: str) -> dict:
        """GET /history/{prompt_id}."""
        r = await self._http.get(f"/history/{prompt_id}", timeout=10.0)
        r.raise_for_status()
        data = r.json()
        return data.get(prompt_id, {})

    # ------------------------------------------------------------------
    # Image retrieval & upload
    # ------------------------------------------------------------------

    async def get_image(self, filename: str, subfolder: str = "", img_type: str = "output") -> bytes:
        """GET /view — download generated image."""
        params = {"filename": filename, "subfolder": subfolder, "type": img_type}
        r = await self._http.get("/view", params=params, timeout=30.0)
        r.raise_for_status()
        return r.content

    async def upload_image(self, image_bytes: bytes, filename: str) -> dict:
        """POST /upload/image — upload input image for img2img."""
        files = {"image": (filename, image_bytes, "image/png")}
        r = await self._http.post("/upload/image", files=files, timeout=30.0)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # High-level generation
    # ------------------------------------------------------------------

    def load_workflow(self, model: str) -> dict:
        """Load and return a deep copy of the workflow template for the given model."""
        filename = WORKFLOW_MAP.get(model)
        if not filename:
            raise ValueError(f"Unknown model '{model}'. Available: {list(WORKFLOW_MAP.keys())}")
        path = WORKFLOWS_DIR / filename
        with open(path) as f:
            return json.load(f)

    def inject_params(self, workflow: dict, params: dict[str, Any]) -> dict:
        """Inject runtime parameters into a workflow template.

        Params:
            prompt: str — text prompt
            width, height: int — image dimensions
            seed: int — random seed (-1 for random)
            steps: int — inference steps
            guidance_scale: float — guidance for FLUX
            denoise: float — denoise strength for img2img
            input_image: str — uploaded image filename for img2img
            negative_prompt: str — negative prompt (SDXL only)
            ckpt_name: str — override checkpoint filename
        """
        wf = copy.deepcopy(workflow)
        prompt = params.get("prompt", "")
        width = params.get("width", 1024)
        height = params.get("height", 1024)
        seed = params.get("seed", -1)
        steps = params.get("steps")
        guidance = params.get("guidance_scale")
        denoise = params.get("denoise")
        input_image = params.get("input_image")
        negative_prompt = params.get("negative_prompt", "")
        ckpt_name = params.get("ckpt_name")

        if seed == -1:
            seed = random.randint(0, 2**32 - 1)

        for node_id, node in wf.items():
            cls = node.get("class_type", "")
            inputs = node.get("inputs", {})

            if cls == "CheckpointLoaderSimple" and ckpt_name:
                inputs["ckpt_name"] = ckpt_name

            if cls == "CLIPTextEncode" and inputs.get("text") == "PROMPT_PLACEHOLDER":
                inputs["text"] = prompt

            if cls == "CLIPTextEncode" and inputs.get("text") == "NEGATIVE_PROMPT_PLACEHOLDER":
                inputs["text"] = negative_prompt

            if cls == "FluxGuidance" and guidance is not None:
                inputs["guidance"] = guidance

            if cls == "EmptyLatentImage":
                inputs["width"] = width
                inputs["height"] = height

            if cls == "KSampler":
                inputs["seed"] = seed
                if steps is not None:
                    inputs["steps"] = steps
                if denoise is not None:
                    inputs["denoise"] = denoise

            if cls == "LoadImage" and input_image:
                inputs["image"] = input_image

        return wf

    async def generate(
        self,
        model: str,
        params: dict[str, Any],
    ) -> tuple[bytes, dict]:
        """Full pipeline: load workflow → inject params → submit → wait → fetch image.

        Returns (image_bytes, metadata_dict).
        """
        if model == "flux-dev-img2img" and not params.get("input_image"):
            raise ValueError("img2img model requires 'input_image' parameter (upload image first via upload_image())")

        workflow = self.load_workflow(model)
        workflow = self.inject_params(workflow, params)

        client_id = uuid.uuid4().hex
        prompt_id = await self.submit_prompt(workflow, client_id)
        history = await self.wait_for_completion(prompt_id, client_id)

        # Extract output image from history
        outputs = history.get("outputs", {})
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                img_info = images[0]
                image_bytes = await self.get_image(
                    filename=img_info["filename"],
                    subfolder=img_info.get("subfolder", ""),
                    img_type=img_info.get("type", "output"),
                )
                metadata = {
                    "prompt_id": prompt_id,
                    "filename": img_info["filename"],
                    "subfolder": img_info.get("subfolder", ""),
                    "seed": params.get("seed", -1),
                    "model": model,
                }
                return image_bytes, metadata

        raise RuntimeError(f"No output images found for prompt {prompt_id}")

    async def close(self):
        await self._http.aclose()
