"""
core/astar.py – Hand-written A* pathfinding algorithm with heapq.

Uses an admissible Euclidean distance heuristic to find the optimal path
while expanding significantly fewer nodes than Dijkstra.

Admissibility proof (viva point):
  h(n) = euclidean_distance(n, dst) / v_max
  Because w_e >= base_time_e >= edge_length / v_max for all edges,
  the straight-line travel time can never exceed the true path travel time:
  h(n) <= h*(n).
  Therefore, A* is guaranteed to return the exact same optimal cost as Dijkstra.
"""

import heapq
import math
import time
from typing import Callable, Optional

import networkx as nx

from core.dijkstra import PathResult


def astar(
    G: nx.MultiDiGraph,
    src: int,
    dst: int,
    weight_fn: Optional[Callable[[int, int, int], float]] = None,
    v_max: float = 1.0,
    explain: bool = False,
) -> PathResult:
    """Compute optimal path from src to dst using A* with Euclidean heuristic.

    Args:
        G: NetworkX MultiDiGraph (projected UTM, with node x, y in metres).
        src: Origin node ID.
        dst: Destination node ID.
        weight_fn: Function (u, v, key) -> weight. If weight == inf, edge is blocked.
                   If None, defaults to edge length.
        v_max: Maximum speed in metres/second for admissible time heuristic.
               Use v_max = 1.0 when weights are lengths in metres.
        explain: If True, records search steps for diagnostic logging.

    Returns:
        PathResult: Container with path node list, cost, distance in metres,
                    and performance counters.
    """
    t_start = time.perf_counter()

    if weight_fn is None:
        def default_weight(u: int, v: int, k: int) -> float:
            return float(G[u][v][k].get("weight", G[u][v][k].get("length", 1.0)))
        weight_fn = default_weight

    # Early exit if src or dst not in graph
    if src not in G or dst not in G:
        t_end = time.perf_counter()
        return PathResult(
            path=[],
            cost=math.inf,
            length_m=0.0,
            explored=0,
            relaxations=0,
            elapsed_ms=(t_end - t_start) * 1000.0,
            trace=[],
        )

    # Trivial case: origin is destination
    if src == dst:
        t_end = time.perf_counter()
        return PathResult(
            path=[src],
            cost=0.0,
            length_m=0.0,
            explored=1,
            relaxations=0,
            elapsed_ms=(t_end - t_start) * 1000.0,
            trace=[{"step": "pop", "node": src, "cost": 0.0}] if explain else [],
        )

    dst_x = G.nodes[dst]["x"]
    dst_y = G.nodes[dst]["y"]
    safe_v_max = max(v_max, 1e-6)

    def heuristic(node: int) -> float:
        """Admissible Euclidean distance heuristic divided by v_max."""
        nd = G.nodes[node]
        dx = dst_x - nd["x"]
        dy = dst_y - nd["y"]
        return math.hypot(dx, dy) / safe_v_max

    # dist[node]: lowest known cost from src to node (g_score)
    dist: dict[int, float] = {src: 0.0}
    # prev: node -> (predecessor_node, edge_key)
    prev: dict[int, tuple[int, int]] = {}

    # Priority queue stores (f_score, g_score, node_id)
    # f_score = g_score + heuristic(node)
    h_src = heuristic(src)
    heap: list[tuple[float, float, int]] = [(h_src, 0.0, src)]

    explored = 0
    relaxations = 0
    trace = []

    while heap:
        f, g, u = heapq.heappop(heap)

        # Stale heap entry check
        if g > dist[u]:
            continue

        explored += 1

        if explain and len(trace) < 12:
            trace.append({
                "step": "pop",
                "node": u,
                "g_cost": round(g, 2),
                "f_cost": round(f, 2),
            })

        # Reached destination: optimal path guaranteed by admissible heuristic
        if u == dst:
            break

        # Relax outgoing edges
        for v in G.adj[u]:
            for key, edge_data in G.adj[u][v].items():
                w = weight_fn(u, v, key)

                # Skip blocked edges
                if math.isinf(w) or w < 0:
                    continue

                relaxations += 1
                tentative_g = g + w

                if tentative_g < dist.get(v, math.inf):
                    dist[v] = tentative_g
                    prev[v] = (u, key)
                    h_v = heuristic(v)
                    f_v = tentative_g + h_v
                    heapq.heappush(heap, (f_v, tentative_g, v))

                    if explain and u == src and len(trace) < 20:
                        trace.append({
                            "step": "relax",
                            "from": u,
                            "to": v,
                            "weight": round(w, 2),
                            "new_g": round(tentative_g, 2),
                            "f_cost": round(f_v, 2),
                        })

    t_end = time.perf_counter()
    elapsed_ms = (t_end - t_start) * 1000.0

    if dst not in dist:
        return PathResult(
            path=[],
            cost=math.inf,
            length_m=0.0,
            explored=explored,
            relaxations=relaxations,
            elapsed_ms=elapsed_ms,
            trace=trace,
        )

    # Reconstruct path and physical distance
    path = []
    curr = dst
    total_length_m = 0.0

    while curr != src:
        path.append(curr)
        p_node, key = prev[curr]
        edge_len = G[p_node][curr][key].get("length", 0.0)
        total_length_m += float(edge_len)
        curr = p_node

    path.append(src)
    path.reverse()

    return PathResult(
        path=path,
        cost=float(dist[dst]),
        length_m=float(total_length_m),
        explored=explored,
        relaxations=relaxations,
        elapsed_ms=elapsed_ms,
        trace=trace,
    )
