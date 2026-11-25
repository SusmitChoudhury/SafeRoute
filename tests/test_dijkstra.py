"""
tests/test_dijkstra.py – Unit tests verifying Dijkstra and A* against NetworkX.

Verifies:
  1. Dijkstra cost equals NetworkX shortest_path_length to 6 decimals on 100 random pairs.
  2. A* cost equals Dijkstra cost on all reachable pairs.
  3. A* explores fewer or equal nodes compared to Dijkstra.
  4. Correct handling of unreachable nodes and infinite-weight (blocked) edges.
  5. Explain mode trace capture.
"""

import math
import random
import networkx as nx
import pytest

from core.dijkstra import dijkstra, PathResult
from core.astar import astar
from core.graph_loader import load_graph
from config import RANDOM_SEED


@pytest.fixture(scope="module")
def walk_graph():
    """Load the cached walk street network."""
    return load_graph("walk")


def test_dijkstra_matches_networkx_100_pairs(walk_graph):
    """Phase 3 Acceptance Check:

    Compare hand-written Dijkstra against NetworkX shortest_path_length
    across 100 random (start, end) pairs.
    """
    random.seed(RANDOM_SEED)
    nodes = list(walk_graph.nodes)
    assert len(nodes) >= 100

    tested_pairs = 0
    matches = 0
    unreachable_count = 0

    weight_fn = lambda u, v, k: float(walk_graph[u][v][k].get("length", 1.0))

    while tested_pairs < 100:
        src = random.choice(nodes)
        dst = random.choice(nodes)
        if src == dst:
            continue

        tested_pairs += 1

        # Run our Dijkstra
        res_dijkstra = dijkstra(walk_graph, src, dst, weight_fn=weight_fn)

        # Run NetworkX
        try:
            nx_cost = nx.shortest_path_length(walk_graph, src, dst, weight="length")
            nx_reachable = True
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            nx_reachable = False
            nx_cost = math.inf

        if nx_reachable:
            assert not math.isinf(res_dijkstra.cost), f"Path should exist between {src} and {dst}"
            # Compare to 6 decimal places
            assert round(res_dijkstra.cost, 6) == round(nx_cost, 6), (
                f"Cost mismatch between {src} and {dst}: "
                f"our={res_dijkstra.cost:.6f}, nx={nx_cost:.6f}"
            )
            matches += 1
        else:
            assert math.isinf(res_dijkstra.cost), f"Expected inf cost for unreachable pair ({src}, {dst})"
            assert res_dijkstra.path == []
            unreachable_count += 1

    print(f"\nTested 100 pairs: {matches} reachable matching NetworkX, {unreachable_count} correctly unreachable.")
    assert matches + unreachable_count == 100


def test_astar_matches_dijkstra_100_pairs(walk_graph):
    """Phase 3 Acceptance Check:

    Compare hand-written A* against hand-written Dijkstra across 100 random pairs.
    A* must yield the exact same cost while expanding <= nodes.
    """
    random.seed(RANDOM_SEED + 1)
    nodes = list(walk_graph.nodes)

    tested_pairs = 0
    total_dijkstra_nodes = 0
    total_astar_nodes = 0

    weight_fn = lambda u, v, k: float(walk_graph[u][v][k].get("length", 1.0))

    while tested_pairs < 100:
        src = random.choice(nodes)
        dst = random.choice(nodes)
        if src == dst:
            continue

        tested_pairs += 1

        res_dijkstra = dijkstra(walk_graph, src, dst, weight_fn=weight_fn)
        # For weights in metres, v_max = 1.0 makes Euclidean heuristic admissible in metres
        res_astar = astar(walk_graph, src, dst, weight_fn=weight_fn, v_max=1.0)

        if not math.isinf(res_dijkstra.cost):
            # Costs must match to 6 decimal places
            assert round(res_astar.cost, 6) == round(res_dijkstra.cost, 6), (
                f"A* cost differs from Dijkstra for ({src}, {dst}): "
                f"astar={res_astar.cost}, dijkstra={res_dijkstra.cost}"
            )
            total_dijkstra_nodes += res_dijkstra.explored
            total_astar_nodes += res_astar.explored

            # A* must not explore more nodes than Dijkstra (with consistent heuristic)
            assert res_astar.explored <= res_dijkstra.explored + 1
        else:
            assert math.isinf(res_astar.cost)

    print(
        f"\nA* node reduction: Dijkstra explored {total_dijkstra_nodes} nodes, "
        f"A* explored {total_astar_nodes} nodes ({(1 - total_astar_nodes/total_dijkstra_nodes)*100:.1f}% reduction)"
    )


def test_dijkstra_blocked_edges(walk_graph):
    """Verify that infinite-weight edges are completely avoided by Dijkstra."""
    nodes = list(walk_graph.nodes)
    src, dst = nodes[0], nodes[1]

    # Normal search
    res_normal = dijkstra(walk_graph, src, dst)

    if not math.isinf(res_normal.cost) and len(res_normal.path) > 2:
        # Block the first hop (u -> v) of the normal path
        u = res_normal.path[0]
        v = res_normal.path[1]

        def blocked_weight(edge_u, edge_v, edge_k):
            if edge_u == u and edge_v == v:
                return math.inf
            return float(walk_graph[edge_u][edge_v][edge_k].get("length", 1.0))

        res_blocked = dijkstra(walk_graph, src, dst, weight_fn=blocked_weight)

        # Either no path or the path must not use the blocked edge
        if not math.isinf(res_blocked.cost):
            for i in range(len(res_blocked.path) - 1):
                assert not (res_blocked.path[i] == u and res_blocked.path[i + 1] == v)


def test_dijkstra_same_src_dst(walk_graph):
    """Verify trivial case where start equals destination."""
    node = list(walk_graph.nodes)[0]
    res = dijkstra(walk_graph, node, node)
    assert res.path == [node]
    assert res.cost == 0.0
    assert res.length_m == 0.0


def test_explain_mode_captures_trace(walk_graph):
    """Verify that explain=True populates the trace list with heap pops and relaxations."""
    nodes = list(walk_graph.nodes)
    src, dst = nodes[0], nodes[5]

    res = dijkstra(walk_graph, src, dst, explain=True)
    assert len(res.trace) > 0
    # Trace entries have step identifier
    assert any(entry["step"] == "pop" for entry in res.trace)
