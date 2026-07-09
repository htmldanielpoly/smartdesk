"""System test — the whole stack, end to end (lecture: System testing).

This is the highest-fidelity test: it talks to the *running* product through
the public gateway only (like a real user would), covering the full journey
register -> ticket -> AI classification -> admin promotion -> queue claim ->
copilot -> comments -> status machine -> forums.

It reuses the proven journey in ``scripts/smoke_test.py`` (a single source of
truth also run by CI) and asserts it passes. If no stack is reachable at
``SMARTDESK_URL`` (default http://localhost:8080) the test SKIPS rather than
fails, so the unit/integration/security suites stay runnable without Docker.

Run against a live stack:
    docker compose up --build -d
    pytest tests/System_Tests -s
"""
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

BASE = os.environ.get("SMARTDESK_URL", "http://localhost:8080")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SMOKE = REPO_ROOT / "scripts" / "smoke_test.py"


def _stack_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


@pytest.fixture(scope="module")
def live_stack():
    if not _stack_is_up():
        pytest.skip(
            f"No SmartDesk stack reachable at {BASE}. "
            "Start it with `docker compose up -d` (or set SMARTDESK_URL)."
        )


def test_full_user_journey_end_to_end(live_stack):
    """The full smoke journey through the public gateway must pass."""
    result = subprocess.run(
        [sys.executable, str(SMOKE), BASE],
        capture_output=True,
        text=True,
        timeout=600,
    )
    # Surface the smoke-test log so failures are diagnosable in pytest output.
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, "End-to-end smoke journey failed"
    assert "SMOKE TEST PASSED" in result.stdout
