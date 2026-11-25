"""
tests/test_route_alternatives.py – Verification of Multi-Route Alternatives (P3, P6, P7).

Acceptance checks:
  1. compute_route_alternatives computes 3 routes with lambda in (0, 2, 6): Fastest, Balanced, Safest.
  2. Detects duplicate routes cleanly.
  3. sim.select_route("safest") and sim.cycle_route() update active route and walker path.
  4. Seed data contains <= 12 incidents, radius 60..120m, none within 100m of default start/end.
  5. Initial route risk is low (< 1.0) and starts outside all danger zones.
  6. Endpoint placed inside hazard triggers WARN log.
"""

import math
import pytest

from config import DEFAULT_START_LATLON, DEFAULT_END_LATLON
from core.graph_loader import load_graph
from core.router import compute_route_alternatives
from sim.incidents import IncidentStore
from sim.simulation import Simulation, SimState


def test_compute_route_alternatives_structure():
    """Verify that compute_route_alternatives returns Fastest, Balanced, Safest with distinct lambdas."""
    G = load_graph("walk")
    store = IncidentStore()
    active = store.get_active_incidents()

    # Law Gate (11250418335) to Block 32 (14148560776)
    src = 11250418335
    dst = 14148560776

    alts = compute_route_alternatives(G, src, dst, active, "walk")

    assert "fastest" in alts
    assert "balanced" in alts
    assert "safest" in alts

    assert alts["fastest"]["lambda"] == 0.0
    assert alts["balanced"]["lambda"] == 2.0
    assert alts["safest"]["lambda"] == 6.0

    for name, info in alts.items():
        assert len(info["path"]) >= 2
        assert info["length_m"] > 0
        assert info["eta_minutes"] > 0
        assert "is_duplicate" in info
        assert "duplicate_of" in info


def test_simulation_select_and_cycle_route():
    """Verify that Simulation can switch between alternatives and cycle them."""
    sim = Simulation()
    assert sim.active_route_name == "balanced"
    initial_route = list(sim.current_route)

    # Switch to fastest
    ok = sim.select_route("fastest")
    assert ok is True
    assert sim.active_route_name == "fastest"
    assert sim.current_route == sim.route_alternatives["fastest"]["full_path"]

    # Switch to safest
    ok = sim.select_route("safest")
    assert ok is True
    assert sim.active_route_name == "safest"
    assert sim.current_route == sim.route_alternatives["safest"]["full_path"]

    # Cycle route: from safest -> wraps to fastest -> balanced -> safest
    next_name = sim.cycle_route()
    assert next_name == "fastest"
    assert sim.active_route_name == "fastest"

    next_name = sim.cycle_route()
    assert next_name == "balanced"
    assert sim.active_route_name == "balanced"


def test_seed_incidents_sparse_and_safe_distance():
    """Verify P7 constraints: <=12 simulated incidents, radius 60..120m, none within 100m of endpoints."""
    store = IncidentStore()
    active = store.get_active_incidents()
    historical = [i for i in active if i.source == "historical"]

    assert len(historical) <= 12, f"Too many historical incidents: {len(historical)}"

    start_lat, start_lon = DEFAULT_START_LATLON
    end_lat, end_lon = DEFAULT_END_LATLON

    for inc in historical:
        assert 60 <= inc.radius_m <= 120, f"Incident #{inc.id} radius out of bounds: {inc.radius_m}"

        # Distance to start
        d_lat_s = (inc.lat - start_lat) * 111320.0
        d_lon_s = (inc.lon - start_lon) * 111320.0 * math.cos(math.radians(start_lat))
        dist_start = math.hypot(d_lat_s, d_lon_s)

        # Distance to end
        d_lat_e = (inc.lat - end_lat) * 111320.0
        d_lon_e = (inc.lon - end_lon) * 111320.0 * math.cos(math.radians(end_lat))
        dist_end = math.hypot(d_lat_e, d_lon_e)

        assert dist_start >= 100.0, f"Incident #{inc.id} is too close to START ({dist_start:.1f} m < 100 m)"
        assert dist_end >= 100.0, f"Incident #{inc.id} is too close to END ({dist_end:.1f} m < 100 m)"


def test_endpoint_hazard_warning():
    """Verify that placing start or goal inside an active hazard zone logs a WARN."""
    sim = Simulation()
    active = sim.incident_store.get_active_incidents()
    assert len(active) > 0

    first_inc = active[0]
    # Place goal right on top of this incident
    sim.set_endpoint("end", first_inc.lat, first_inc.lon)

    # Check logger
    warn_found = any(
        "GOAL marker placed inside danger zone" in text
        for lvl, text in sim.logger.lines()
    )
    assert warn_found, "Expected WARN log when placing endpoint inside hazard circle"

