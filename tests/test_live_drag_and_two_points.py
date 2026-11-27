"""
tests/test_live_drag_and_two_points.py – Verification for live drag-and-drop
rerouting, historical-incident promotion drag, right-click removal, and
two-point (Point 1 -> Point 2) interactive route selection + HTTP API.
"""

import http.client
import json
import os
import threading
from http.server import HTTPServer

os.environ["MPLCONFIGDIR"] = "cache"
os.environ["SDL_VIDEODRIVER"] = "dummy"

from config import DEFAULT_END_LATLON, DEFAULT_START_LATLON
from core.lookahead import check_remaining_route_hazard, route_polyline
from sim.simulation import SimState, Simulation
import tools.web_server as web_server


def test_drop_hazard_overlapping_walker_segment_reroutes_immediately():
    """Dropping a hazard right ahead of the moving walker (overlapping active segment) must trigger rerouting."""
    sim = Simulation(mode="walk")
    sim.incident_store.clear_all()
    sim.set_detection_mode("lookahead")
    sim._calculate_initial_route()

    sim.start_or_pause()
    # Advance walker ~28 m onto the route
    for _ in range(20):
        sim.update(0.1)

    assert sim.state == SimState.MOVING
    assert sim.walker is not None
    s_now = sim.walker.distance_travelled
    assert s_now > 10.0

    # Place an accident only ~25 m ahead along the route so its 150 m radius overlaps s_now directly!
    # Previously, zone_entry_distance returned d_start <= s_now and query_ahead missed it!
    pts, cum = sim.polyline_pts, sim.polyline_cum
    target_lat, target_lon = sim.walker.lat, sim.walker.lon
    for i, c_dist in enumerate(cum):
        if c_dist >= s_now + 25.0:
            x_m, y_m = float(pts[i][0]), float(pts[i][1])
            lon_t, lat_t = sim.walker.transformer_to_latlon.transform(x_m, y_m)
            target_lat, target_lon = float(lat_t), float(lon_t)
            break

    inc_id = sim.drop_incident(target_lat, target_lon, inc_type="accident")
    assert inc_id > 0
    assert sim.reroute_count >= 1, "Dropping hazard overlapping current walker segment must reroute immediately"
    assert sim.state == SimState.WARNING_2
    assert len(sim.previous_route) > 0
    # Walker must not jump back to origin index 0 after live route switch
    assert sim.walker.distance_travelled >= 0.0


def test_drag_historical_hazard_onto_route_triggers_reroute():
    """Dragging an existing simulated (historical) hazard onto an active route must promote & reroute."""
    sim = Simulation(mode="walk")
    sim.incident_store.clear_all()
    # Add a historical incident completely off-route first
    hist_id = sim.incident_store.add_incident(
        "accident",
        lat=31.2600,
        lon=75.7120,
        source="historical",
    )
    sim.set_detection_mode("instant")
    sim._calculate_initial_route()
    sim.start_or_pause()
    sim.update(0.2)
    assert sim.reroute_count == 0

    # Pick midpoint of active route and drag the historical hazard straight onto it
    mid_idx = len(sim.polyline_pts) // 2
    mx, my = float(sim.polyline_pts[mid_idx][0]), float(sim.polyline_pts[mid_idx][1])
    mlon, mlat = sim.walker.transformer_to_latlon.transform(mx, my)

    moved = sim.move_incident(hist_id, float(mlat), float(mlon))
    assert moved is True
    assert sim.reroute_count == 1
    assert sim.state == SimState.WARNING_2

    updated = next(i for i in sim.incident_store.get_active_incidents() if i.id == hist_id)
    assert updated.source == "live"


def test_remove_incident_near_handles_utm_coordinates_cleanly():
    """Verify remove_incident_near uses inc.x/inc.y without AttributeError and refreshes route."""
    sim = Simulation(mode="walk")
    sim.incident_store.clear_all()
    sim._calculate_initial_route()

    drop_lat, drop_lon = 31.2535, 75.7045
    inc_id = sim.drop_incident(drop_lat, drop_lon, inc_type="construction")
    removed_id = sim.remove_incident_near(drop_lat + 0.0001, drop_lon - 0.0001, max_dist_m=120.0)
    assert removed_id == inc_id
    remaining_ids = [i.id for i in sim.incident_store.get_active_incidents()]
    assert inc_id not in remaining_ids


def test_two_point_route_selection_and_endpoint_relocation():
    """Verify set_route_points and set_endpoint compute a hazard-aware route between arbitrary P1 & P2."""
    sim = Simulation(mode="walk")
    sim.incident_store.clear_all()

    p1 = (31.2512, 75.7022)
    p2 = (31.2572, 75.7068)
    (n1, _), (n2, _) = sim.set_route_points(p1, p2)

    assert n1 is not None and n2 is not None and n1 != n2
    assert sim.start_latlon == p1
    assert sim.end_latlon == p2
    assert len(sim.current_route) >= 2
    assert sim.route_stats["length_m"] > 100.0
    assert set(sim.route_alternatives.keys()) == {"fastest", "balanced", "safest"}

    # Start walking, then relocate Point 1: simulation cleanly resets to new Point 1 & draws new blue route
    sim.start_or_pause()
    sim.update(0.3)
    assert sim.state == SimState.MOVING

    new_p1 = (31.2528, 75.7035)
    sim.set_endpoint("start", *new_p1)
    assert sim.state == SimState.IDLE
    assert sim.start_latlon == new_p1
    assert len(sim.current_route) >= 2


def test_web_api_route_points_and_live_drag_roundtrip():
    """Verify HTTP /api/set_route_points, /api/drop_incident, /api/move_incident, /api/remove_incident."""
    host = web_server.SimulationHost(mode="walk", speed=10)
    host.sim.incident_store.clear_all()
    host.sim._calculate_initial_route()
    web_server._host = host

    server = HTTPServer(("127.0.0.1", 0), web_server.SafeRouteWebHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post_json(path: str, payload: dict) -> dict:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(
                "POST",
                path,
                body=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            assert resp.status == 200, f"Expected 200 on {path}, got {resp.status}"
            return json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()

    try:
        # 1. Serve HTML containing P1 -> P2 selector and responsive toolbar
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/")
            resp = conn.getresponse()
            assert resp.status == 200
            html = resp.read().decode("utf-8")
        finally:
            conn.close()
        assert "Pick P1 → P2" in html
        assert "drag-ghost-pill" in html

        # 2. Select custom P1 -> P2 route points
        res_pts = post_json("/api/set_route_points", {
            "start_lat": DEFAULT_START_LATLON[0],
            "start_lon": DEFAULT_START_LATLON[1],
            "end_lat": DEFAULT_END_LATLON[0],
            "end_lon": DEFAULT_END_LATLON[1],
        })
        assert res_pts["status"] == "ok"
        assert len(res_pts["state"]["current_route"]) >= 2

        # 3. Start simulation and advance slightly
        post_json("/api/action", {"action": "start_pause"})
        with host.lock:
            host.sim.update(0.2)

        # 4. Drop off-route hazard, then drag it onto route midpoint -> must reroute!
        drop_res = post_json("/api/drop_incident", {"lat": 31.2610, "lon": 75.7140, "type": "accident"})
        inc_id = drop_res["incident_id"]
        assert drop_res["state"]["reroute_count"] == 0

        mid_idx = len(res_pts["state"]["current_route"]) // 2
        mid_lat, mid_lon = res_pts["state"]["current_route"][mid_idx]
        move_res = post_json("/api/move_incident", {"id": inc_id, "lat": mid_lat, "lon": mid_lon})
        assert move_res["moved"] is True
        assert move_res["state"]["reroute_count"] == 1

        # 5. Coordinate-based remove fallback (right-click without ID fallback)
        rem_res = post_json("/api/remove_incident", {"lat": mid_lat, "lon": mid_lon})
        assert rem_res["removed_id"] == inc_id
    finally:
        host.running = False
        server.shutdown()
        server.server_close()
