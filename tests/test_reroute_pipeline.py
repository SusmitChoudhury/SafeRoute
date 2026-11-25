"""
tests/test_reroute_pipeline.py – Proof for P4: Real-time 6-Step Reroute Pipeline & Detection Modes.

Verifies:
  1. The 6-step numbered log pipeline executes in real-time (< 100 ms) when a hazard is dropped.
  2. The exact numbered steps (STEP 1/6 to STEP 6/6) and DONE are logged with required formulas.
  3. Detection mode toggle (Instant vs 500m Lookahead) controls whether hazards beyond 500 m
     trigger immediately or wait until the look-ahead window.
  4. Old route is preserved in previous_route so the UI can fade it to a grey dashed line.
"""

import os
os.environ["MPLCONFIGDIR"] = "cache"
os.environ["SDL_VIDEODRIVER"] = "dummy"

import time
import pytest

from sim.simulation import SimState, Simulation


def test_6_step_reroute_pipeline_execution_and_speed():
    """Verify the 6-step numbered rerouting pipeline executes under 100 ms and logs every step."""
    sim = Simulation(mode="walk")
    sim.incident_store.clear_live_incidents()
    sim.set_detection_mode("instant")

    # Start moving
    sim.start_or_pause()
    sim.update(0.2)

    # Drop an accident ahead along the corridor
    t_start = time.perf_counter()
    inc_id = sim.drop_incident(31.2550, 75.7043, inc_type="accident")
    pipeline_ms = (time.perf_counter() - t_start) * 1000

    print(f"\n[Proof P4] Total pipeline execution time: {pipeline_ms:.2f} ms (budget: < 100 ms)")
    assert pipeline_ms < 100.0, f"Reroute pipeline took {pipeline_ms:.2f} ms, exceeding 100 ms budget!"

    # Verify simulation state transitioned
    assert sim.state == SimState.WARNING_2
    assert sim.reroute_count >= 1
    assert len(sim.previous_route) > 0, "previous_route must be preserved for grey dashed map rendering"

    # Verify all 6 steps are logged with exact identifiers
    logged_levels = [lvl for lvl, txt in sim.logger.lines()]
    logged_texts = [txt for lvl, txt in sim.logger.lines()]

    assert any("STEP 1/6" in lvl for lvl in logged_levels), "Missing STEP 1/6 (detect) in logs"
    assert any("STEP 2/6" in lvl for lvl in logged_levels), "Missing STEP 2/6 (weights) in logs"
    assert any("STEP 3/6" in lvl for lvl in logged_levels), "Missing STEP 3/6 (search) in logs"
    assert any("STEP 4/6" in lvl for lvl in logged_levels), "Missing STEP 4/6 (options) in logs"
    assert any("STEP 5/6" in lvl for lvl in logged_levels), "Missing STEP 5/6 (compare) in logs"
    assert any("STEP 6/6" in lvl for lvl in logged_levels), "Missing STEP 6/6 (switch) in logs"
    assert any("DONE" in lvl for lvl in logged_levels), "Missing DONE (reroute) in logs"

    # Verify formulas and content
    weights_log = next(txt for lvl, txt in sim.logger.lines() if "STEP 2/6" in lvl)
    assert "edges affected" in weights_log and "worst:" in weights_log

    search_log = next(txt for lvl, txt in sim.logger.lines() if "STEP 3/6" in lvl)
    assert "explored" in search_log and "relaxations" in search_log

    options_log = next(txt for lvl, txt in sim.logger.lines() if "STEP 4/6" in lvl)
    assert "Fastest" in options_log and "Balanced" in options_log and "Safest" in options_log

    done_log = next(txt for lvl, txt in sim.logger.lines() if "DONE" in lvl)
    assert "SHORTCUT:" in done_log


def test_detection_mode_instant_vs_lookahead():
    """Verify Instant mode triggers immediately, while Lookahead (500m) waits for the window."""
    # 1. Lookahead mode on longer route (~1576m): dropping at end (>1000m away) does not trigger
    sim_la = Simulation(mode="walk")
    sim_la.incident_store.clear_all()
    sim_la.set_endpoint("end", 31.2650, 75.7000)
    sim_la.set_detection_mode("lookahead")
    sim_la.start_or_pause()
    sim_la.update(0.1)

    # Drop incident at far destination (~1500 m away from start)
    sim_la.drop_incident(31.2650, 75.7000, inc_type="accident")
    # Distance gap to end is > 1000 m, so in 500m lookahead mode it must not trigger yet
    assert sim_la.reroute_count == 0, "Lookahead 500m mode should not trigger for incident > 500 m away"

    # 2. Instant mode: dropping anywhere on the remaining route triggers immediately
    sim_inst = Simulation(mode="walk")
    sim_inst.incident_store.clear_all()
    sim_inst.set_endpoint("end", 31.2650, 75.7000)
    sim_inst.set_detection_mode("instant")
    sim_inst.start_or_pause()
    sim_inst.update(0.1)

    sim_inst.drop_incident(31.2650, 75.7000, inc_type="accident")
    assert sim_inst.reroute_count == 1, "Instant mode must trigger reroute immediately upon drop"
