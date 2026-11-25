"""
core/dijkstra.py – Hand-written Dijkstra's algorithm with priority queue (heapq).

Implements Dijkstra's single-source shortest path algorithm using a binary min-heap.
Provides diagnostic counters (explored nodes, edge relaxations, elapsed time)
and an explain mode that logs internal search steps for educational demonstration.

Hard constraints:
  - Written from scratch with heapq; NetworkX is never called here.
  - MultiDiGraph aware: tracks the exact edge key chosen between parallel edges.
  - Adheres strictly to the PathResult dataclass contract in Section 10 of the plan.
"""

from dataclasses import dataclass, field
import heapq
import math
import time
from typing import Callable, Optional

import networkx as nx


@dataclass
class PathResult:
    """Standardized output structure for graph search algorithms."""
    path: list[int]
    cost: float
    length_m: float
    explored: int
    relaxations: int
    elapsed_ms: float
    trace: list = field(default_factory=list)


def dijkstra(
    G: nx.MultiDiGraph,
    src: int,
    dst: int,
    weight_fn: Optional[Callable[[int, int, int], float]] = None,
    explain: bool = False,
) -> PathResult:
    """Compute the shortest path from src to dst using Dijkstra's algorithm.

    Args:
        G: NetworkX MultiDiGraph (projected, with edge attributes).
        src: Origin node ID.
        dst: Destination node ID.
        weight_fn: Function (u, v, key) -> weight. If weight == inf, edge is blocked.
                   If None, defaults to edge length.
        explain: If True, records the first 12 queue pops and initial relaxations
                 for the live algorithm log.

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
            trace=[{"step": "pop", "node": src, "distance": 0.0}] if explain else [],
        )

    # dist: node -> best known tentative distance from src
    dist: dict[int, float] = {src: 0.0}
    # prev: node -> (predecessor_node, edge_key)
    prev: dict[int, tuple[int, int]] = {}

    # Priority queue storing (tentative_distance, node_id)
    heap: list[tuple[float, int]] = [(0.0, src)]

    explored = 0
    relaxations = 0
    trace = []

    while heap:
        d, u = heapq.heappop(heap)

        # Stale heap entry check (lazy deletion)
        if d > dist[u]:
            continue

        explored += 1

        if explain and len(trace) < 12:
            trace.append({"step": "pop", "node": u, "distance": round(d, 2)})

        # Reached destination: shortest path found
        if u == dst:
            break

        # Explore outgoing edges (MultiDiGraph supports parallel edges via keys)
        for v in G.adj[u]:
            for key, edge_data in G.adj[u][v].items():
                w = weight_fn(u, v, key)

                # Skip blocked or infinite weight edges
                if math.isinf(w) or w < 0:
                    continue

                relaxations += 1
                tentative = d + w

                if tentative < dist.get(v, math.inf):
                    dist[v] = tentative
                    prev[v] = (u, key)
                    heapq.heappush(heap, (tentative, v))

                    if explain and u == src and len(trace) < 20:
                        trace.append({
                            "step": "relax",
                            "from": u,
                            "to": v,
                            "weight": round(w, 2),
                            "new_dist": round(tentative, 2),
                        })

    t_end = time.perf_counter()
    elapsed_ms = (t_end - t_start) * 1000.0

    # If destination was not reached
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
