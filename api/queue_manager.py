"""Job queue manager with background worker and GPU pause support."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cloud_router import CloudRouter
    from comfyui_client import ComfyUIClient

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    status: str  # queued | processing | completed | failed | cancelled
    request: dict
    result: bytes | None = None
    result_metadata: dict | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    completed_at: str | None = None


class JobQueue:
    def __init__(
        self,
        router: CloudRouter,
        comfyui: ComfyUIClient | None = None,
        max_jobs: int = 50,
        result_ttl: float = 600.0,
        idle_vram_timeout: float = 300.0,
    ):
        self._router = router
        self._comfyui = comfyui
        self._max_jobs = max_jobs
        self._result_ttl = result_ttl
        self._idle_vram_timeout = idle_vram_timeout

        self._queue: deque[str] = deque()  # job IDs in order
        self._jobs: dict[str, Job] = {}
        self._gpu_paused = False
        self._wake = asyncio.Event()
        self._worker_task: asyncio.Task | None = None
        self._idle_timer_task: asyncio.Task | None = None
        self._last_activity_at: float = time.monotonic()
        self._vram_freed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._worker_task = asyncio.create_task(self._worker_loop())
        if self._comfyui and self._idle_vram_timeout > 0:
            self._idle_timer_task = asyncio.create_task(self._idle_timer_loop())
        logger.info("Job queue worker started (idle VRAM timeout: %.0fs)", self._idle_vram_timeout)

    async def stop(self):
        for task in (self._worker_task, self._idle_timer_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("Job queue worker stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, request: dict) -> Job:
        if len(self._jobs) >= self._max_jobs:
            self._cleanup()
            if len(self._jobs) >= self._max_jobs:
                raise RuntimeError("Job queue is full")

        self._vram_freed = False
        job = Job(id=uuid.uuid4().hex, status="queued", request=request)
        self._jobs[job.id] = job
        self._queue.append(job.id)
        self._wake.set()
        logger.info("Job %s queued (position %d)", job.id[:8], len(self._queue))
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def get_position(self, job_id: str) -> int:
        """1-based queue position. 0 = processing. -1 = not in queue."""
        job = self._jobs.get(job_id)
        if not job:
            return -1
        if job.status == "processing":
            return 0
        if job.status == "queued":
            try:
                return list(self._queue).index(job_id) + 1
            except ValueError:
                return -1
        return -1

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status != "queued":
            return False
        job.status = "cancelled"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        try:
            self._queue.remove(job_id)
        except ValueError:
            pass
        logger.info("Job %s cancelled", job_id[:8])
        return True

    def set_gpu_paused(self, paused: bool):
        self._gpu_paused = paused
        if not paused:
            self._wake.set()
        logger.info("GPU paused: %s", paused)

    @property
    def gpu_paused(self) -> bool:
        return self._gpu_paused

    def queue_info(self) -> dict:
        processing = sum(1 for j in self._jobs.values() if j.status == "processing")
        queued = len(self._queue)
        return {
            "total_queued": queued,
            "processing": processing,
            "gpu_paused": self._gpu_paused,
        }

    async def free_vram(self) -> bool:
        """Immediately free VRAM by unloading models."""
        if self._comfyui:
            ok = await self._comfyui.free_memory()
            if ok:
                self._vram_freed = True
                logger.info("VRAM freed (manual)")
            return ok
        return False

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    async def _worker_loop(self):
        while True:
            try:
                await self._wake.wait()
                self._wake.clear()

                while self._queue:
                    # Wait while GPU is paused (unless cloud fallback is available)
                    while self._gpu_paused:
                        if self._router.fal_key or self._router.runpod_api_key:
                            break  # Cloud router will handle fallback
                        await asyncio.sleep(2.0)

                    if not self._queue:
                        break

                    job_id = self._queue[0]
                    job = self._jobs.get(job_id)

                    if not job or job.status != "queued":
                        self._queue.popleft()
                        continue

                    self._queue.popleft()
                    job.status = "processing"
                    job.started_at = datetime.now(timezone.utc).isoformat()
                    logger.info("Job %s processing", job_id[:8])

                    try:
                        image_bytes, metadata = await self._router.generate(**job.request)
                        job.result = image_bytes
                        job.result_metadata = metadata
                        job.status = "completed"
                        logger.info("Job %s completed (source=%s)", job_id[:8], metadata.get("source"))
                    except Exception as e:
                        job.error = str(e)
                        job.status = "failed"
                        logger.error("Job %s failed: %s", job_id[:8], e)
                    finally:
                        job.completed_at = datetime.now(timezone.utc).isoformat()
                        self._last_activity_at = time.monotonic()

                    self._cleanup()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker loop error")
                await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Idle VRAM timer
    # ------------------------------------------------------------------

    async def _idle_timer_loop(self):
        """Periodically check if GPU is idle and free VRAM after timeout."""
        while True:
            try:
                await asyncio.sleep(30.0)
                if self._vram_freed or self._gpu_paused:
                    continue
                if self._queue or any(j.status == "processing" for j in self._jobs.values()):
                    continue
                elapsed = time.monotonic() - self._last_activity_at
                if elapsed >= self._idle_vram_timeout:
                    logger.info("Idle %.0fs — freeing VRAM", elapsed)
                    if await self._comfyui.free_memory():
                        self._vram_freed = True
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Idle timer error")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self):
        """Remove completed/failed jobs older than TTL."""
        now = datetime.now(timezone.utc)
        to_delete = []
        for job_id, job in self._jobs.items():
            if job.status not in ("completed", "failed", "cancelled"):
                continue
            if not job.completed_at:
                continue
            try:
                completed = datetime.fromisoformat(job.completed_at)
                age = (now - completed).total_seconds()
                if age > self._result_ttl:
                    to_delete.append(job_id)
            except (ValueError, TypeError):
                pass
        for job_id in to_delete:
            del self._jobs[job_id]
            logger.debug("Evicted job %s (TTL expired)", job_id[:8])
