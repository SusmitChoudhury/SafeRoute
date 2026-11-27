"""
01_Main_Algorithms_Viva/run_core_algorithms_demo.py

Clean, standalone teacher-facing & viva demonstration of SafeRoute's Part 1
(Main Algorithms Engine) directly importing from core/ without any UI or simulation clutter.

Algorithms demonstrated:
  1. OSM Projected Graph & Coordinate Snapping (core/graph_loader.py)
  2. Dijkstra Shortest Path vs A* Heuristic Search (core/dijkstra.py, core/astar.py)
  3. Composite Edge Risk Model (core/risk_model.py)
  4. Multi-Criteria Route Options (lambda = 0 Fastest, 2 Balanced, 6 Safest) (core/router.py)
  5. Look-Ahead Line-Circle Quadratic Intersection + bisect_left (core/lookahead.py)
"""

from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / ".cache" / "matplotlib"))

from config import DEFAULT_END_LATLON, DEFAULT_START_LATLON, LOOKAHEAD_M
from core.astar import astar
from core.dijkstra import dijkstra
from core.graph_loader import load_graph, snap_to_node
from core.lookahead import (
    build_entry_index,
    check_remaining_route_hazard,
    query_ahead,
    route_polyline,
)
from core.risk_model import Incident, compute_edge_risk, make_weight_fn
from core.router import compare_modes, compute_route_alternatives
from core.travel_model import MODE_SPEED_MPS, add_travel_times


def main() -> None:
    print("=" * 72)
    print("  SafeRoute (CSM216) - Part 1: Main Algorithms Viva Demonstration")
    print("=" * 72)

    # 1. Load projected UTM graph & snap endpoints
    mode = "walk"
    G = load_graph(mode)
    add_travel_times(G, mode)
    src, d_src = snap_to_node(G, *DEFAULT_START_LATLON)
    dst, d_dst = snap_to_node(G, *DEFAULT_END_LATLON)
    print(f"\n[1] Projected Road Graph ({mode.upper()}, EPSG:32643 UTM metres)")
    print(f"    Nodes: {G.number_of_nodes()} | Edges: {G.number_of_edges()}")
    print(f"    Start node: {src} (snap {d_src:.1f} m) -> Goal node: {dst} (snap {d_dst:.1f} m)")

    # 2. Baseline Dijkstra vs A* comparison
    empty_risks = compute_edge_risk(G, [], mode)
    base_weight_fn = make_weight_fn(G, empty_risks, mode, [], lam=2.0)
    d_res = dijkstra(G, src, dst, weight_fn=base_weight_fn)
    a_res = astar(G, src, dst, weight_fn=base_weight_fn, v_max=MODE_SPEED_MPS[mode])

    print("\n[2] Baseline Optimal Search: Dijkstra vs. A*")
    print(
        f"    Dijkstra : length={d_res.length_m:.1f} m | cost={d_res.cost:.2f} s "
        f"| explored={d_res.explored} nodes | time={d_res.elapsed_ms:.2f} ms"
    )
    print(
        f"    A*       : length={a_res.length_m:.1f} m | cost={a_res.cost:.2f} s "
        f"| explored={a_res.explored} nodes | time={a_res.elapsed_ms:.2f} ms"
    )
    assert abs(d_res.cost - a_res.cost) < 1e-6, "A* must match Dijkstra optimal cost"

    # 3. Drop a simulated live accident mid-route & score risk + alternatives
    pts, cum = route_polyline(G, d_res.path)
    mid_idx = len(pts) // 2
    mid_x, mid_y = float(pts[mid_idx][0]), float(pts[mid_idx][1])
    live_accident = Incident(
        id=99,
        type="accident",
        x=mid_x,
        y=mid_y,
        severity=4,
        radius_m=150.0,
        blocking=True,
        source="live",
    )
    incidents = [live_accident]
    risks = compute_edge_risk(G, incidents, mode)
    affected = sum(1 for r in risks.values() if r > 0.0)
    alts = compute_route_alternatives(G, src, dst, incidents, mode, risks=risks)

    print("\n[3] Risk Scoring & Multi-Criteria Alternatives (accident radius 150 m)")
    print(f"    Edges with non-zero risk score: {affected}")
    for key in ("fastest", "balanced", "safest"):
        info = alts[key]
        print(
            f"    {info['name']:8s} (lambda={info['lambda']}): "
            f"{info['length_m']:6.1f} m | {info['eta_minutes']:4.1f} min | "
            f"risk={info['risk']:5.2f} | same_as_prev={info['is_duplicate']}"
        )

    # 4. Look-Ahead Line-Circle Quadratic Intersection + bisect_left query
    entry_index = build_entry_index(pts, cum, incidents)
    s_now = float(cum[max(0, mid_idx - 2)])
    hits_bisect = query_ahead(entry_index, s_now=0.0, lookahead_m=LOOKAHEAD_M)
    remaining_hit = check_remaining_route_hazard(pts, cum, s_now=s_now, inc=live_accident, horizon_m=LOOKAHEAD_M)

    print("\n[4] Look-Ahead Binary Search (500 m horizon)")
    print(f"    Entry keys sorted (m): {[round(k, 1) for k in entry_index.entry_keys]}")
    print(f"    Hits within {LOOKAHEAD_M:.0f} m of s=0.0 m : {hits_bisect}")
    print(f"    Remaining-route check at s={s_now:.1f} m: triggers at s_enter={remaining_hit:.1f} m")

    # 5. Multi-Modal Comparison
    etas = compare_modes(DEFAULT_START_LATLON, DEFAULT_END_LATLON, incidents)
    print("\n[5] Multi-Modal Comparison (Walk / Bike / Car under active hazard)")
    for m in ("walk", "bike", "car"):
        st = etas[m]
        print(f"    {m.upper():4s}: {st['length_m']:6.1f} m | ETA = {st['eta_minutes']:.2f} min")

    print("\nAll core algorithm checks completed cleanly.")


if __name__ == "__main__":
    main()
