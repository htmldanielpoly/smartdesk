"""Tests for the AI job scheduler: priority ordering, real parallelism,
backpressure, timeouts, and the HTTP surface. No model is ever loaded."""
import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import model_manager
from app.services import scheduler as sched_mod
from app.services.scheduler import Overloaded, Scheduler, priority_for


def run(coro):
    return asyncio.run(coro)


# --- priority mapping ----------------------------------------------------------

def test_interactive_work_outranks_batch_work():
    assert priority_for("copilot", "LOW") < priority_for("classify", "URGENT")
    assert priority_for("auto_resolve", "MEDIUM") < priority_for("duplicates", "URGENT")
    assert priority_for("classify", "URGENT") < priority_for("classify", "LOW")
    assert priority_for("cluster", None) > priority_for("classify", "LOW")


def test_unknown_priority_is_treated_as_medium():
    assert priority_for("classify", "weird") == priority_for("classify", "MEDIUM")
    assert priority_for("classify", None) == priority_for("classify", "medium")


# --- ordering ------------------------------------------------------------------

def test_jobs_run_in_priority_order_not_arrival_order(monkeypatch):
    monkeypatch.setattr(settings, "ai_workers", 1)
    order: list[str] = []
    gate = threading.Event()

    def blocker():
        gate.wait(timeout=5)
        return "blocker"

    def job(name):
        order.append(name)
        return name

    async def main():
        s = Scheduler()
        s.start()
        # Occupy the single worker, then enqueue in "wrong" order.
        first = asyncio.ensure_future(s.submit("classify", blocker, ticket_priority="URGENT"))
        await asyncio.sleep(0.05)
        low = asyncio.ensure_future(
            s.submit("classify", job, "classify LOW", ticket_priority="LOW")
        )
        urgent = asyncio.ensure_future(
            s.submit("copilot", job, "copilot URGENT", ticket_priority="URGENT")
        )
        medium = asyncio.ensure_future(
            s.submit("classify", job, "classify MEDIUM", ticket_priority="MEDIUM")
        )
        cluster = asyncio.ensure_future(s.submit("cluster", job, "cluster"))
        await asyncio.sleep(0.05)
        gate.set()
        await asyncio.gather(first, low, urgent, medium, cluster)
        await s.stop()
        return s.stats()

    stats = run(main())
    assert order == ["copilot URGENT", "classify MEDIUM", "classify LOW", "cluster"]
    assert stats["completed"] == 5
    assert stats["by_kind"] == {"classify": 3, "copilot": 1, "cluster": 1}


# --- parallelism ---------------------------------------------------------------

def test_worker_pool_runs_jobs_in_parallel(monkeypatch):
    monkeypatch.setattr(settings, "ai_workers", 4)
    barrier = threading.Barrier(4, timeout=5)

    def job():
        # Only completes if all four are running at the same time.
        barrier.wait()
        return threading.get_ident()

    async def main():
        s = Scheduler()
        s.start()
        started = time.monotonic()
        results = await asyncio.gather(*(s.submit("classify", job) for _ in range(4)))
        elapsed = time.monotonic() - started
        await s.stop()
        return results, elapsed

    results, elapsed = run(main())
    assert len(set(results)) == 4  # four distinct threads
    assert elapsed < 4


def test_event_loop_stays_responsive_while_jobs_run(monkeypatch):
    monkeypatch.setattr(settings, "ai_workers", 1)

    def slow():
        time.sleep(0.3)
        return "done"

    async def main():
        s = Scheduler()
        s.start()
        fut = asyncio.ensure_future(s.submit("classify", slow))
        ticks = 0
        while not fut.done():
            await asyncio.sleep(0.02)
            ticks += 1
        await s.stop()
        return ticks, await fut

    ticks, result = run(main())
    assert result == "done"
    assert ticks >= 5  # the loop kept turning during the blocking job


# --- backpressure and timeouts ------------------------------------------------

def test_full_queue_rejects_immediately(monkeypatch):
    monkeypatch.setattr(settings, "ai_workers", 1)
    monkeypatch.setattr(settings, "ai_queue_max", 1)
    gate = threading.Event()

    def blocker():
        gate.wait(timeout=5)

    async def main():
        s = Scheduler()
        s.start()
        running = asyncio.ensure_future(s.submit("classify", blocker))
        await asyncio.sleep(0.05)
        queued = asyncio.ensure_future(s.submit("classify", lambda: "q"))
        await asyncio.sleep(0.01)
        with pytest.raises(Overloaded):
            await s.submit("classify", lambda: "rejected")
        stats_before = s.stats()
        gate.set()
        await asyncio.gather(running, queued)
        await s.stop()
        return stats_before, s.stats()

    before, after = run(main())
    assert before["queued"] == 1 and before["running"] == 1 and before["rejected"] == 1
    assert after["completed"] == 2


def test_job_timeout_raises_and_is_counted(monkeypatch):
    monkeypatch.setattr(settings, "ai_workers", 1)
    monkeypatch.setattr(settings, "ai_job_timeout_seconds", 0.05)

    def slow():
        time.sleep(0.3)

    async def main():
        s = Scheduler()
        s.start()
        with pytest.raises(TimeoutError):
            await s.submit("copilot", slow)
        await asyncio.sleep(0.35)  # let the thread finish so stop() is clean
        stats = s.stats()
        await s.stop()
        return stats

    stats = run(main())
    assert stats["timed_out"] == 1


def test_worker_survives_a_failing_job(monkeypatch):
    monkeypatch.setattr(settings, "ai_workers", 1)

    def boom():
        raise ValueError("model exploded")

    async def main():
        s = Scheduler()
        s.start()
        with pytest.raises(ValueError):
            await s.submit("classify", boom)
        ok = await s.submit("classify", lambda: "still alive")
        stats = s.stats()
        await s.stop()
        return ok, stats

    ok, stats = run(main())
    assert ok == "still alive"
    assert stats["failed"] == 1 and stats["completed"] == 2 and stats["workers"] == 1


# --- HTTP surface --------------------------------------------------------------

def test_endpoints_go_through_the_scheduler_and_health_reports_it(monkeypatch):
    # Run the real lifespan (worker pool started once, like production) but
    # never download models in a unit test.
    monkeypatch.setattr(model_manager, "prepare", lambda: None)
    with TestClient(app) as client:
        r = client.post(
            "/classify",
            json={"title": "Refund", "description": "invoice", "priority": "URGENT"},
        )
        assert r.status_code == 200 and r.json()["category"] == "Billing"

        stats = client.get("/health").json()["scheduler"]
        assert stats["workers"] == settings.ai_workers
        assert stats["completed"] >= 1
        assert stats["by_kind"].get("classify", 0) >= 1


def test_saturated_engine_answers_503_with_retry_after(monkeypatch):
    monkeypatch.setattr(sched_mod.scheduler, "submit", _always_overloaded)
    r = TestClient(app).post("/classify", json={"title": "a", "description": "b"})
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "5"


def test_stuck_job_answers_504(monkeypatch):
    async def _timeout(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(sched_mod.scheduler, "submit", _timeout)
    r = TestClient(app).post("/copilot", json={"title": "a", "description": "b"})
    assert r.status_code == 504


async def _always_overloaded(*args, **kwargs):
    raise Overloaded("full")
