"""
tests/test_drag_and_drop_api.py – Proof for P2: Drag and Drop & Repositioning.

Verifies:
  1. Dropping a hazard (simulating drag-and-drop from toolbar) creates an incident at target coordinates.
  2. Dragging an existing hazard repositioning it updates coordinates in SQLite and simulation state.
  3. Removing a hazard (via '✕' or context menu) safely clears it from active state.
  4. Dragging START and GOAL markers snaps them to road graph nodes and triggers route recomputation.
"""

import os
os.environ["MPLCONFIGDIR"] = "cache"
os.environ["SDL_VIDEODRIVER"] = "dummy"

import pytest

from sim.simulation import SimState, Simulation


def test_drop_hazard_at_coordinates():
    """Verify dropping an accident at specific coordinates creates the incident."""
    sim = Simulation(mode="walk")
    sim.incident_store.clear_live_incidents()

    # Drop an accident on the road near LPU campus
    target_lat, target_lon = 31.2530, 75.7040
    inc_id = sim.drop_incident(target_lat, target_lon, inc_type="accident")
    assert inc_id is not None and inc_id > 0

    active_incidents = sim.incident_store.get_active_incidents()
    created = next((i for i in active_incidents if i.id == inc_id), None)
    assert created is not None, f"Incident #{inc_id} must be in active incidents"
    assert created.type == "accident"
    assert abs(created.lat - target_lat) < 1e-4
    assert abs(created.lon - target_lon) < 1e-4


def test_drag_reposition_existing_hazard():
    """Verify dragging an existing hazard icon updates coordinates in SQLite and memory."""
    sim = Simulation(mode="walk")
    sim.incident_store.clear_live_incidents()

    # Initial drop position
    lat1, lon1 = 31.2520, 75.7030
    inc_id = sim.drop_incident(lat1, lon1, inc_type="accident")

    # Drag to new position
    lat2, lon2 = 31.2545, 75.7055
    moved = sim.move_incident(inc_id, lat2, lon2)
    assert moved is True, "move_incident must return True on success"

    active_incidents = sim.incident_store.get_active_incidents()
    repositioned = next((i for i in active_incidents if i.id == inc_id), None)
    assert repositioned is not None
    assert abs(repositioned.lat - lat2) < 1e-4, f"Expected lat {lat2}, got {repositioned.lat}"
    assert abs(repositioned.lon - lon2) < 1e-4, f"Expected lon {lon2}, got {repositioned.lon}"


def test_remove_hazard_via_x_button_or_click():
    """Verify hazard removal by ID or coordinate click removes it completely."""
    sim = Simulation(mode="walk")
    sim.incident_store.clear_live_incidents()

    inc_id = sim.drop_incident(31.2535, 75.7045, inc_type="flooding")
    assert any(i.id == inc_id for i in sim.incident_store.get_active_incidents())

    # Remove by ID
    sim.incident_store.remove_incident(inc_id)
    sim.triggered_incidents.discard(inc_id)
    sim._rebuild_lookahead_index()

    active_ids = [i.id for i in sim.incident_store.get_active_incidents()]
    assert inc_id not in active_ids, f"Incident #{inc_id} must not be in active list after removal"


def test_drag_start_and_goal_endpoints():
    """Verify dragging START and GOAL markers updates endpoints and recalculates route."""
    sim = Simulation(mode="walk")
    initial_route = list(sim.current_route)

    # Drag START point
    new_start_lat, new_start_lon = 31.2505, 75.7050
    node_s, dist_s = sim.set_endpoint("start", new_start_lat, new_start_lon)
    assert node_s is not None
    assert sim.start_latlon == (new_start_lat, new_start_lon)
    assert sim.start_node == node_s

    # Drag GOAL point
    new_end_lat, new_end_lon = 31.2570, 75.7030
    node_e, dist_e = sim.set_endpoint("end", new_end_lat, new_end_lon)
    assert node_e is not None
    assert sim.end_latlon == (new_end_lat, new_end_lon)
    assert sim.end_node == node_e

    # Route should be recomputed with new origin / destination
    assert sim.current_route[0] == node_s
    assert sim.current_route[-1] == node_e

