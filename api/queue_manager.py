"""Job queue manager with background worker and GPU pause support."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cloud_router import CloudRouter

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
        max_jobs: int = 50,
        result_ttl: float = 600.0,
    ):
        self._router = router
        self._max_jobs = max_jobs
        self._result_ttl = result_ttl

        self._queue: deque[str] = deque()  # job IDs in order
        self._jobs: dict[str, Job] = {}
        self._gpu_paused = False
        self._wake = asyncio.Event()
        self._worker_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Job queue worker started")

    async def stop(self):
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
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

                    self._cleanup()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker loop error")
                await asyncio.sleep(1.0)

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
