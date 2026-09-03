"""Priority scheduling for local-LLM work (the parallel-programming core).

Why
---
The local models are CPU-bound and llama.cpp instances are not thread-safe,
so naive concurrency either serialises everything behind one lock or
crashes. The guideline asks for "parallel programming techniques to handle
the local LLM and the priority queue of chats", and for the product to "work
well even when many clients are texting at once".

How
---
* Every AI request becomes a *job* on an ``asyncio.PriorityQueue``. The
  ordering key is ``(priority, sequence)``: a smaller number wins, FIFO
  within a level. ``priority = kind base + ticket priority``, so an URGENT
  ticket's copilot draft is served before a LOW ticket's classification, and
  interactive work (an agent or a customer is waiting on it) beats batch
  work (incident clustering).
* A pool of worker tasks (AI_WORKERS) pulls jobs and runs each in a thread
  via ``asyncio.to_thread``. The event loop stays free to accept requests
  and answer ``/health`` while inference runs.
* The two models have *separate* locks (see llm_local), so an embedding job
  and a chat completion run truly in parallel on different cores, and the
  rule-based fallbacks need no lock at all.
* Backpressure: a full queue (AI_QUEUE_MAX) rejects immediately with
  ``Overloaded`` (the gateway then uses its rule-based path), and every job
  has a timeout (AI_JOB_TIMEOUT_SECONDS), so a burst can never pile up
  unbounded work or hang a caller.

Stats are exposed on ``/health`` (queued, running, completed, rejected,
timed out, average wait, per kind) so the behaviour is observable live.
"""
import asyncio
import itertools
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Lower wins. Interactive kinds (someone is waiting) sit above batch kinds.
KIND_BASE: dict[str, int] = {
    "copilot": 0,        # an agent is looking at the screen
    "auto_resolve": 0,   # a customer just submitted and could be answered now
    "duplicates": 10,    # agent-triggered, but a lookup, not a reply
    "classify": 20,      # background, result lands on the ticket later
    "cluster": 30,       # staff overview, whole-batch work
}
TICKET_PRIORITY: dict[str, int] = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


class Overloaded(Exception):
    """The queue is full; the caller should fall back rather than wait."""


def priority_for(kind: str, ticket_priority: str | None) -> int:
    base = KIND_BASE.get(kind, 20)
    level = TICKET_PRIORITY.get((ticket_priority or "MEDIUM").upper(), TICKET_PRIORITY["MEDIUM"])
    return base + level


@dataclass(order=True)
class _Job:
    priority: int
    seq: int
    kind: str = field(compare=False)
    fn: Callable[..., Any] = field(compare=False)
    args: tuple = field(compare=False)
    future: asyncio.Future = field(compare=False)
    enqueued_at: float = field(compare=False)


class Scheduler:
    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[_Job] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._workers: list[asyncio.Task] = []
        self._seq = itertools.count()
        self._running = 0
        self._completed = 0
        self._rejected = 0
        self._timed_out = 0
        self._failed = 0
        self._wait_total = 0.0
        self._by_kind: Counter[str] = Counter()

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Create the queue and the worker pool on the current event loop."""
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._queue = asyncio.PriorityQueue(maxsize=settings.ai_queue_max)
        self._workers = [
            loop.create_task(self._worker(i), name=f"ai-worker-{i}")
            for i in range(max(1, settings.ai_workers))
        ]
        logger.info("AI scheduler started: %d workers, queue max %d",
                    len(self._workers), settings.ai_queue_max)

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._workers = []
        self._queue = None
        self._loop = None

    def _ensure_started(self) -> None:
        # Lazily (re)start on the loop that is actually running: tests build
        # a fresh loop per client and never run the lifespan.
        loop = asyncio.get_running_loop()
        if self._queue is None or self._loop is not loop or all(t.done() for t in self._workers):
            self.start()

    # --- submission --------------------------------------------------------

    async def submit(
        self, kind: str, fn: Callable[..., Any], *args: Any, ticket_priority: str | None = None
    ) -> Any:
        """Queue ``fn(*args)`` and wait for its result.

        Raises ``Overloaded`` when the queue is full and ``TimeoutError``
        when the job does not finish within AI_JOB_TIMEOUT_SECONDS.
        """
        self._ensure_started()
        assert self._queue is not None and self._loop is not None
        job = _Job(
            priority=priority_for(kind, ticket_priority),
            seq=next(self._seq),
            kind=kind,
            fn=fn,
            args=args,
            future=self._loop.create_future(),
            enqueued_at=time.monotonic(),
        )
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            self._rejected += 1
            raise Overloaded(f"AI queue full ({settings.ai_queue_max} jobs)") from None

        try:
            return await asyncio.wait_for(job.future, timeout=settings.ai_job_timeout_seconds)
        except TimeoutError:
            self._timed_out += 1
            raise

    # --- workers -----------------------------------------------------------

    async def _worker(self, index: int) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            try:
                if job.future.done():  # caller gave up (timed out) while queued
                    continue
                self._wait_total += time.monotonic() - job.enqueued_at
                self._running += 1
                try:
                    # Inference is blocking CPU work: run it off the event loop.
                    result = await asyncio.to_thread(job.fn, *job.args)
                except Exception as exc:  # noqa: BLE001 - surface to the caller
                    self._failed += 1
                    if not job.future.done():
                        job.future.set_exception(exc)
                else:
                    if not job.future.done():
                        job.future.set_result(result)
                finally:
                    self._running -= 1
                    self._completed += 1
                    self._by_kind[job.kind] += 1
            finally:
                self._queue.task_done()

    # --- observability -----------------------------------------------------

    def stats(self) -> dict:
        completed = self._completed
        return {
            "workers": len([t for t in self._workers if not t.done()]),
            "queue_max": settings.ai_queue_max,
            "queued": self._queue.qsize() if self._queue is not None else 0,
            "running": self._running,
            "completed": completed,
            "rejected": self._rejected,
            "timed_out": self._timed_out,
            "failed": self._failed,
            "avg_wait_ms": round(1000 * self._wait_total / completed, 1) if completed else 0.0,
            "by_kind": dict(self._by_kind),
        }


scheduler = Scheduler()
