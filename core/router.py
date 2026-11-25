"""
core/router.py – High-level routing orchestrator: compute_route, compare_modes, reroute.

Encapsulates the complete pathfinding workflow:
  - Computes optimal risk-weighted paths with A*.
  - Compares travel times and distances across walk, bike, and car.
  - Dynamically recalculates routes when danger is detected ahead,
    quantifying the extra distance, extra time, and risk reduction.
"""

import math
from typing import Optional

import networkx as nx

from config import (
    CAR_SPEED_DEFAULTS_KMH,
    LAMBDA_RISK,
    WALK_SPEED_MPS,
    BIKE_SPEED_MPS,
)
from core.astar import astar
from core.dijkstra import dijkstra, PathResult
from core.graph_loader import load_graph, snap_to_node
from core.risk_model import (
    Incident,
    compute_edge_risk,
    make_weight_fn,
)
from core.travel_model import (
    MODE_SPEED_MPS,
    add_travel_times,
    calculate_route_stats,
)


def compute_route(
    G: nx.MultiDiGraph,
    src: int,
    dst: int,
    incidents: list[Incident],
    mode: str,
    explain: bool = False,
) -> PathResult:
    """Compute the optimal safe route from src to dst.

    Args:
        G: Projected NetworkX MultiDiGraph.
        src: Origin node ID.
        dst: Destination node ID.
        incidents: List of active Incident objects.
        mode: Travel mode ('walk', 'bike', 'car', or 'drive').
        explain: If True, captures search steps for live logging.

    Returns:
        PathResult: Optimal path, cost in seconds, and distance in metres.
    """
    normalized_mode = "car" if mode in ("car", "drive") else mode
    risks = compute_edge_risk(G, incidents, normalized_mode)
    weight_fn = make_weight_fn(G, risks, normalized_mode, incidents, fallback=False)

    v_max = 50.0 / 3.6 if normalized_mode == "car" else MODE_SPEED_MPS.get(normalized_mode, 1.39)
    result = astar(G, src, dst, weight_fn=weight_fn, v_max=v_max, explain=explain)

    # If blocked by incidents, try penalty fallback
    if math.isinf(result.cost) or not result.path:
        weight_fn_fb = make_weight_fn(G, risks, normalized_mode, incidents, fallback=True)
        result = astar(G, src, dst, weight_fn=weight_fn_fb, v_max=v_max, explain=explain)

    return result


def compare_modes(
    origin_latlon: tuple[float, float],
    dest_latlon: tuple[float, float],
    incidents: list[Incident],
) -> dict[str, dict]:
    """Compare travel distance and ETA across all three modes (walk, bike, car).

    Args:
        origin_latlon: (lat, lon) of start point.
        dest_latlon: (lat, lon) of destination.
        incidents: Active Incident objects.

    Returns:
        dict: Mapping mode -> {"length_m": float, "eta_seconds": float, "eta_minutes": float}
    """
    comparisons = {}

    for m in ["walk", "bike", "car"]:
        try:
            G_m = load_graph(m)
            add_travel_times(G_m, m)
            src, _ = snap_to_node(G_m, *origin_latlon)
            dst, _ = snap_to_node(G_m, *dest_latlon)

            res = compute_route(G_m, src, dst, incidents, m)
            stats = calculate_route_stats(G_m, res.path, m)
            comparisons[m] = stats
        except Exception:
            comparisons[m] = {"length_m": 0.0, "eta_seconds": 0.0, "eta_minutes": 0.0}

    return comparisons


def reroute(
    G: nx.MultiDiGraph,
    current_node_ahead: int,
    dst: int,
    incidents: list[Incident],
    mode: str,
    old: Optional[PathResult] = None,
) -> tuple[PathResult, dict]:
    """Calculate a safe detour from the traveller's upcoming junction to destination.

    Formula & Rule (Section 6.8):
      1. Next node ahead becomes the new origin (traveller cannot teleport).
      2. Recompute edge risks with the new danger zone.
      3. Run A* to find detour avoiding danger.
      4. Compare old vs new: extra distance, extra time, risk reduction.

    Args:
        G: Active graph.
        current_node_ahead: Upcoming graph node on traveller's current edge.
        dst: Final destination node.
        incidents: All active Incident objects (including newly detected).
        mode: Travel mode.
        old: Previous PathResult to compare against.

    Returns:
        tuple[PathResult, dict]: New route result and comparison metrics dict.
    """
    new_res = compute_route(G, current_node_ahead, dst, incidents, mode)

    old_cost = old.cost if old else new_res.cost
    old_length = old.length_m if old else new_res.length_m

    extra_distance_m = max(0.0, new_res.length_m - old_length)
    extra_time_s = max(0.0, new_res.cost - old_cost)

    # Compute risk reduction
    normalized_mode = "car" if mode in ("car", "drive") else mode
    risks = compute_edge_risk(G, incidents, normalized_mode)

    old_path = old.path if old else []
    old_risk_sum = 0.0
    for i in range(len(old_path) - 1):
        u, v = old_path[i], old_path[i + 1]
        if G.has_edge(u, v):
            k = next(iter(G[u][v]))
            old_risk_sum += risks.get((u, v, k), 0.0)

    new_risk_sum = 0.0
    for i in range(len(new_res.path) - 1):
        u, v = new_res.path[i], new_res.path[i + 1]
        if G.has_edge(u, v):
            k = next(iter(G[u][v]))
            new_risk_sum += risks.get((u, v, k), 0.0)

    comparison = {
        "extra_distance_m": extra_distance_m,
        "extra_time_s": extra_time_s,
        "extra_time_min": extra_time_s / 60.0,
        "old_risk": old_risk_sum,
        "new_risk": new_risk_sum,
    }

    return new_res, comparison


def compute_route_alternatives(
    G: nx.MultiDiGraph,
    src: int,
    dst: int,
    incidents: list[Incident],
    mode: str,
    risks: Optional[dict[tuple[int, int, int], float]] = None,
) -> dict[str, dict]:
    """Compute candidate routes: Fastest (lambda=0), Balanced (lambda=2), Safest (lambda=6).

    Args:
        G: Projected graph.
        src: Origin node.
        dst: Destination node.
        incidents: Active incidents.
        mode: Travel mode.
        risks: Optional precomputed edge risks dict.

    Returns:
        dict: Mapping {"fastest": info, "balanced": info, "safest": info}.
    """
    normalized_mode = "car" if mode in ("car", "drive") else mode
    if risks is None:
        risks = compute_edge_risk(G, incidents, normalized_mode)

    lambdas = [("fastest", 0.0), ("balanced", 2.0), ("safest", 6.0)]
    results = {}

    for name, lam in lambdas:
        w_fn = make_weight_fn(G, risks, normalized_mode, incidents, lam=lam, fallback=False)
        res = dijkstra(G, src, dst, weight_fn=w_fn)
        if math.isinf(res.cost) or not res.path:
            w_fn_fb = make_weight_fn(G, risks, normalized_mode, incidents, lam=lam, fallback=True)
            res = dijkstra(G, src, dst, weight_fn=w_fn_fb)

        stats = calculate_route_stats(G, res.path, normalized_mode)
        r_sum = 0.0
        for i in range(len(res.path) - 1):
            u, v = res.path[i], res.path[i + 1]
            if G.has_edge(u, v):
                k = next(iter(G[u][v]))
                r_sum += risks.get((u, v, k), 0.0)

        results[name] = {
            "name": name.capitalize(),
            "lambda": lam,
            "path": res.path,
            "length_m": stats.get("length_m", 0.0),
            "eta_minutes": stats.get("eta_minutes", 0.0),
            "cost_s": res.cost,
            "risk": r_sum,
            "explored": res.explored,
            "relaxations": res.relaxations,
            "elapsed_ms": res.elapsed_ms,
            "is_duplicate": False,
            "duplicate_of": None,
        }

    # Mark duplicate geometries
    seen_paths = {}
    for name, _ in lambdas:
        p_tup = tuple(results[name]["path"])
        if p_tup in seen_paths:
            results[name]["is_duplicate"] = True
            results[name]["duplicate_of"] = seen_paths[p_tup]
        else:
            seen_paths[p_tup] = name

    return results
