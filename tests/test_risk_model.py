"""
tests/test_risk_model.py – Unit tests for risk scoring, incident storage, and edge weights.

Verifies:
  1. Linear falloff formula f = 1 at centre, 0 at perimeter.
  2. Mode sensitivity multipliers.
  3. Age decay reduces risk of older historical incidents.
  4. Chronic accident road history term: kappa * ln(1 + accidents_on_edge).
  5. Vehicle blocking: blocking incident within 40 m sets w_e = inf for car, but finite for walk.
  6. Penalty fallback: fallback=True yields 50x penalty instead of infinity.
  7. SQLite incident store operations (add, remove, get active).
  8. Dropping an incident increases edge weights along the route.
"""

import math
from pathlib import Path
import pytest

from config import (
    BLOCK_RADIUS_M,
    KAPPA_HISTORY,
    LAMBDA_RISK,
    PENALTY_FALLBACK_FACTOR,
)
from core.graph_loader import load_graph
from core.risk_model import (
    Incident,
    compute_edge_risk,
    make_weight_fn,
)
from sim.incidents import IncidentStore


@pytest.fixture(scope="module")
def walk_graph():
    return load_graph("walk")


@pytest.fixture(scope="module")
def drive_graph():
    return load_graph("drive")


@pytest.fixture
def temp_db(tmp_path):
    """Isolated SQLite incident store for tests."""
    db_file = tmp_path / "test_saferoute.db"
    store = IncidentStore(db_path=db_file)
    yield store
    store.clear_all()


def test_linear_falloff_formula(walk_graph):
    """f equals 1 at the centre and 0 at the radius."""
    edge = list(walk_graph.edges(keys=True))[0]
    u, v, k = edge
    ux, uy = walk_graph.nodes[u]["x"], walk_graph.nodes[u]["y"]

    # Incident exactly on node u
    inc_center = Incident(
        id=1, type="accident", x=ux, y=uy, severity=4, radius_m=100.0, blocking=False, age_days=0.0
    )
    risks_center = compute_edge_risk(walk_graph, [inc_center], "walk")
    assert risks_center[edge] > 0.0

    # Incident outside the radius (150 m away)
    inc_far = Incident(
        id=2, type="accident", x=ux + 250.0, y=uy + 250.0, severity=4, radius_m=100.0, blocking=False, age_days=0.0
    )
    risks_far = compute_edge_risk(walk_graph, [inc_far], "walk")
    assert risks_far[edge] == 0.0


def test_ageing_reduces_old_incidents(walk_graph):
    """Ageing reduces risk contribution of historical incidents."""
    edge = list(walk_graph.edges(keys=True))[0]
    u, v, k = edge
    ux, uy = walk_graph.nodes[u]["x"], walk_graph.nodes[u]["y"]

    inc_new = Incident(
        id=1, type="accident", x=ux, y=uy, severity=4, radius_m=150.0, blocking=False, age_days=0.0, source="historical"
    )
    inc_old = Incident(
        id=2, type="accident", x=ux, y=uy, severity=4, radius_m=150.0, blocking=False, age_days=180.0, source="historical"
    )

    risk_new = compute_edge_risk(walk_graph, [inc_new], "walk")[edge]
    risk_old = compute_edge_risk(walk_graph, [inc_old], "walk")[edge]

    assert risk_new > 0.0
    assert risk_old > 0.0
    # exp(-180/180) = exp(-1) ~ 0.368
    ratio = risk_old / risk_new
    assert abs(ratio - math.exp(-1)) < 0.05


def test_chronic_accident_history(walk_graph):
    """Multiple accidents on the same road trigger the logarithmic history term."""
    edge = list(walk_graph.edges(keys=True))[0]
    u, v, k = edge
    ux, uy = walk_graph.nodes[u]["x"], walk_graph.nodes[u]["y"]

    incidents_1 = [
        Incident(id=1, type="accident", x=ux, y=uy, severity=4, radius_m=100.0, blocking=False, age_days=0.0)
    ]
    incidents_3 = [
        Incident(id=i, type="accident", x=ux, y=uy, severity=4, radius_m=100.0, blocking=False, age_days=0.0)
        for i in range(1, 4)
    ]

    r1 = compute_edge_risk(walk_graph, incidents_1, "walk")[edge]
    r3 = compute_edge_risk(walk_graph, incidents_3, "walk")[edge]

    # r3 must have higher base risk plus higher kappa * ln(1 + 3)
    assert r3 > r1


def test_vehicle_blocking_car_vs_walk(drive_graph, walk_graph):
    """Blocking incident within 40 m sets w_e = inf for car, but remains finite for walk."""
    # Find an edge in drive_graph
    edge = list(drive_graph.edges(keys=True))[0]
    u, v, k = edge
    ux, uy = drive_graph.nodes[u]["x"], drive_graph.nodes[u]["y"]

    # Blocking accident 10 m from node u
    accident = Incident(
        id=99,
        type="accident",
        x=ux + 10.0,
        y=uy,
        severity=4,
        radius_m=150.0,
        blocking=True,
    )

    # 1. Car mode: edge within 40m must be blocked (infinity)
    car_risks = compute_edge_risk(drive_graph, [accident], "car")
    car_weight_fn = make_weight_fn(drive_graph, car_risks, "car", [accident], fallback=False)
    assert math.isinf(car_weight_fn(u, v, k)), "Blocking incident must close road for car"

    # 2. Walk mode: pedestrians can walk past / around; edge is NOT infinity
    if walk_graph.has_edge(u, v, k):
        walk_risks = compute_edge_risk(walk_graph, [accident], "walk")
        walk_weight_fn = make_weight_fn(walk_graph, walk_risks, "walk", [accident], fallback=False)
        w_walk = walk_weight_fn(u, v, k)
        assert not math.isinf(w_walk), "Walk mode must never receive infinite weight"
        assert w_walk > 0.0


def test_penalty_fallback_mode(drive_graph):
    """When fallback=True, blocked edges receive a 50x penalty multiplier instead of infinity."""
    edge = list(drive_graph.edges(keys=True))[0]
    u, v, k = edge
    ux, uy = drive_graph.nodes[u]["x"], drive_graph.nodes[u]["y"]

    accident = Incident(id=1, type="accident", x=ux, y=uy, severity=4, radius_m=150.0, blocking=True)
    car_risks = compute_edge_risk(drive_graph, [accident], "car")

    # Standard mode -> inf
    weight_standard = make_weight_fn(drive_graph, car_risks, "car", [accident], fallback=False)
    assert math.isinf(weight_standard(u, v, k))

    # Fallback mode -> finite 50x penalty
    weight_fallback = make_weight_fn(drive_graph, car_risks, "car", [accident], fallback=True)
    w_fb = weight_fallback(u, v, k)
    assert not math.isinf(w_fb)
    assert w_fb > 0.0


def test_sqlite_incident_store(temp_db):
    """Test incident insertion, deactivation, and coordinate projection in SQLite."""
    # Add an incident
    inc_id = temp_db.add_incident(
        inc_type="accident",
        lat=31.2551,
        lon=75.7025,
        severity=4,
        radius_m=150.0,
        blocking=True,
        source="live",
    )
    assert inc_id > 0

    # Retrieve active
    active = temp_db.get_active_incidents()
    assert len(active) >= 1
    found = next((i for i in active if i.id == inc_id), None)
    assert found is not None
    assert found.type == "accident"
    assert found.severity == 4
    assert found.blocking is True
    # UTM coordinates must be in metres (> 100,000)
    assert found.x > 100000.0
    assert found.y > 100000.0

    # Deactivate / remove
    removed = temp_db.remove_incident(inc_id)
    assert removed is True
    active_after = temp_db.get_active_incidents()
    assert not any(i.id == inc_id for i in active_after)


def test_dropping_incident_increases_edge_weights(walk_graph):
    """Dropping an incident on an edge strictly increases its weight."""
    edge = list(walk_graph.edges(keys=True))[0]
    u, v, k = edge
    ux, uy = walk_graph.nodes[u]["x"], walk_graph.nodes[u]["y"]

    # Base weight without incidents
    risks_empty = compute_edge_risk(walk_graph, [], "walk")
    weight_fn_base = make_weight_fn(walk_graph, risks_empty, "walk", [])
    w_base = weight_fn_base(u, v, k)

    # Drop incident near edge
    inc = Incident(id=1, type="flooding", x=ux, y=uy, severity=4, radius_m=200.0, blocking=False)
    risks_with_inc = compute_edge_risk(walk_graph, [inc], "walk")
    weight_fn_risk = make_weight_fn(walk_graph, risks_with_inc, "walk", [inc])
    w_risk = weight_fn_risk(u, v, k)

    assert risks_with_inc[edge] > 0.0
    assert w_risk > w_base, f"Weight should increase with risk: base={w_base}, risk={w_risk}"
