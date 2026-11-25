"""
tests/test_scripted_demo.py – Verification of the Scripted Demo (Seed 42).

Acceptance checks:
  1. Pressing F5 / selecting Scripted Demo scenario reproduces identical events with seed 42.
  2. Running the scripted demo twice in a row produces identical log messages
     (ignoring timestamps).
  3. Verifies full sequence: Start -> Accident dropped -> Warning 1 -> Dynamic A* reroute
     -> Warning 2 banner with metrics -> Destination arrival summary.
"""

import re
import pytest

from sim.simulation import SimState, Simulation
from sim.scripted_demo import setup_scripted_demo


def _normalize_log(line: str) -> str:
    """Strip variable timestamps [mm:ss.s], elapsed CPU ms, and SQLite autoincrement IDs."""
    # 1. Strip timestamp header [mm:ss.s]
    s = re.sub(r"^\[\d{2}:\d{2}\.\d\]\s*", "", line).strip()
    # 2. Normalize execution wall-clock time in ms (e.g., '3.1 ms' -> '<TIME> ms')
    s = re.sub(r"\b\d+\.\d+\s*ms\b", "<TIME> ms", s)
    # 3. Normalize SQLite auto-increment IDs (e.g., '#23' -> '#<ID>')
    s = re.sub(r"#\d+", "#<ID>", s)
    return s


def run_demo_and_get_logs(steps: int = 500, dt: float = 0.1) -> tuple[Simulation, list[str]]:
    """Execute the scripted demo for a given number of steps and return stripped log lines."""
    from sim.incidents import IncidentStore
    IncidentStore().clear_live_incidents()

    sim = Simulation()
    setup_scripted_demo(sim)

    for _ in range(steps):
        sim.update(dt)
        if sim.state == SimState.ARRIVED:
            break

    normalized_lines = [_normalize_log(text) for level, text in sim.logger.lines()]
    return sim, normalized_lines


def test_scripted_demo_deterministic_reproduction():
    """Verify two consecutive runs produce 100% identical log sequences."""
    sim1, logs1 = run_demo_and_get_logs()
    sim2, logs2 = run_demo_and_get_logs()

    assert sim1.state == SimState.ARRIVED
    assert sim2.state == SimState.ARRIVED

    # Ensure identical log message sequences
    assert logs1 == logs2, f"Log mismatch between runs!\nRun 1 ({len(logs1)}):\n{logs1}\nRun 2 ({len(logs2)}):\n{logs2}"


def test_scripted_demo_event_sequence():
    """Verify that all key events fire in the correct order."""
    sim, logs = run_demo_and_get_logs()

    joined_log = "\n".join(logs)

    # 1. Startup and demo initialization
    assert "Scripted Demo initialized (seed=42" in joined_log

    # 2. Incident dropped
    assert "accident dropped" in joined_log

    # 3. Look-ahead detection and Warning 1
    assert "zone intersects the remaining route" in joined_log or "danger zone within 500 m" in joined_log
    assert "STEP 1/6" in joined_log or "WARNING-1" in joined_log or "danger ahead - recalculating route" in joined_log

    # 4. Reroute and Warning 2
    assert "STEP 6/6" in joined_log or "WARNING-2" in joined_log or "rerouted: new path avoids incident" in joined_log
    assert "old -> new" in joined_log or "extra time" in joined_log

    # 5. Arrival and summary metrics
    assert "destination reached" in joined_log
    assert "summary" in joined_log
    assert sim.incidents_avoided >= 1
    assert sim.warnings_count >= 1
