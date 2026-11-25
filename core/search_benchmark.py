"""
core/search_benchmark.py – Algorithm performance benchmarking for CSM216 Project.

Benchmarks:
  1. Look-ahead Search: Linear scan O(N) vs Binary Search O(log N + k)
     Evaluated over synthetic incident datasets from N = 10 to N = 100,000.
  2. Pathfinding: Custom Dijkstra vs A* on the OpenStreetMap graph
     Compares explored nodes, priority-queue relaxations, and runtime (ms).

Produces publication-ready charts saved to docs/ for the viva presentation.
"""

import bisect
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set local Matplotlib cache directory before importing matplotlib
os.environ["MPLCONFIGDIR"] = str(PROJECT_ROOT / ".cache" / "matplotlib")
(PROJECT_ROOT / ".cache" / "matplotlib").mkdir(parents=True, exist_ok=True)

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from config import LOOKAHEAD_M
from core.astar import astar
from core.dijkstra import dijkstra
from core.graph_loader import load_graph
from core.travel_model import MODE_SPEED_MPS, add_travel_times


def run_search_benchmark(
    sizes: Optional[list[int]] = None,
    repeats: int = 500,
) -> dict[str, list[float]]:
    """Benchmark linear scan vs binary search on sorted look-ahead entry keys.

    Args:
        sizes: List of incident count sizes (default: 10 to 100,000).
        repeats: Number of random query repeats per size to obtain stable timing.

    Returns:
        dict: Benchmarking results containing sizes, linear_us, and binary_us.
    """
    if sizes is None:
        sizes = [10, 50, 100, 500, 1000, 5000, 10000, 50000, 100000]

    linear_times_us = []
    binary_times_us = []

    print("Running Look-Ahead Search Benchmark (Linear vs Binary Search)...")

    for N in sizes:
        # Generate synthetic sorted entry keys along a 100 km corridor
        max_dist = max(10000.0, float(N) * 20.0)
        entry_keys = sorted(random.uniform(0.0, max_dist) for _ in range(N))
        entry_ids = list(range(1, N + 1))

        # Sample query positions
        queries = [random.uniform(0.0, max_dist - LOOKAHEAD_M) for _ in range(repeats)]

        # 1. Linear scan timing
        t0 = time.perf_counter()
        for s_now in queries:
            s_end = s_now + LOOKAHEAD_M
            hits_lin = [
                entry_ids[i]
                for i in range(N)
                if s_now <= entry_keys[i] <= s_end
            ]
        t1 = time.perf_counter()
        linear_avg_us = ((t1 - t0) / repeats) * 1e6
        linear_times_us.append(linear_avg_us)

        # 2. Binary search (bisect_left) timing
        t0 = time.perf_counter()
        for s_now in queries:
            s_end = s_now + LOOKAHEAD_M
            lo = bisect.bisect_left(entry_keys, s_now)
            hits_bin = []
            while lo < N and entry_keys[lo] <= s_end:
                hits_bin.append(entry_ids[lo])
                lo += 1
        t1 = time.perf_counter()
        binary_avg_us = ((t1 - t0) / repeats) * 1e6
        binary_times_us.append(binary_avg_us)

        speedup = linear_avg_us / max(1e-9, binary_avg_us)
        print(f"  N = {N:7d} | Linear: {linear_avg_us:8.2f} us | Binary: {binary_avg_us:6.2f} us | Speedup: {speedup:6.1f}x")

    return {
        "sizes": sizes,
        "linear_us": linear_times_us,
        "binary_us": binary_times_us,
    }


def run_pathfinding_benchmark(
    num_pairs: int = 50,
    mode: str = "walk",
) -> dict[str, list]:
    """Benchmark Dijkstra vs A* on random OD pairs across the real street network.

    Args:
        num_pairs: Number of connected OD pairs to test.
        mode: Graph travel mode ('walk', 'bike', 'car').

    Returns:
        dict: Pathfinding metrics for both algorithms.
    """
    print(f"\nRunning Pathfinding Benchmark: Dijkstra vs A* on '{mode}' graph...")
    G = load_graph(mode)
    add_travel_times(G, mode)

    # Use largest strongly connected component
    components = list(nx.strongly_connected_components(G))
    largest_cc = max(components, key=len)
    cc_nodes = list(largest_cc)

    random.seed(42)
    pairs = []
    attempts = 0
    while len(pairs) < num_pairs and attempts < num_pairs * 10:
        attempts += 1
        u, v = random.sample(cc_nodes, 2)
        if nx.has_path(G, u, v):
            pairs.append((u, v))

    v_max = 50.0 / 3.6 if mode in ("car", "drive") else MODE_SPEED_MPS.get(mode, 1.39)

    dijkstra_nodes = []
    astar_nodes = []
    dijkstra_ms = []
    astar_ms = []
    costs = []

    for idx, (u, v) in enumerate(pairs):
        d_res = dijkstra(G, u, v)
        a_res = astar(G, u, v, v_max=v_max)

        # Confirm admissibility and optimality
        assert math.isclose(d_res.cost, a_res.cost, rel_tol=1e-5), f"Cost mismatch: {d_res.cost} != {a_res.cost}"

        dijkstra_nodes.append(d_res.explored)
        astar_nodes.append(a_res.explored)
        dijkstra_ms.append(d_res.elapsed_ms)
        astar_ms.append(a_res.elapsed_ms)
        costs.append(d_res.cost)

    avg_d_nodes = np.mean(dijkstra_nodes)
    avg_a_nodes = np.mean(astar_nodes)
    savings = (1.0 - (avg_a_nodes / avg_d_nodes)) * 100.0

    print(f"  Tested {len(pairs)} pairs:")
    print(f"  Dijkstra explored avg: {avg_d_nodes:.1f} nodes ({np.mean(dijkstra_ms):.2f} ms)")
    print(f"  A* explored avg:       {avg_a_nodes:.1f} nodes ({np.mean(astar_ms):.2f} ms)")
    print(f"  A* Node Reduction:     {savings:.1f}% fewer nodes explored")

    return {
        "pairs": pairs,
        "dijkstra_nodes": dijkstra_nodes,
        "astar_nodes": astar_nodes,
        "dijkstra_ms": dijkstra_ms,
        "astar_ms": astar_ms,
        "costs": costs,
        "reduction_pct": savings,
    }


def plot_search_benchmark(results: dict, out_path: Path) -> None:
    """Plot Linear vs Binary Search runtime comparison."""
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)

    sizes = results["sizes"]
    lin = results["linear_us"]
    bin_srch = results["binary_us"]

    ax.plot(sizes, lin, "o-", color="#e74c3c", linewidth=2.2, label=r"Linear Scan $O(N)$")
    ax.plot(sizes, bin_srch, "s-", color="#2980b9", linewidth=2.2, label=r"Binary Search $O(\log N + k)$")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("Look-Ahead Danger Zone Query: Linear vs Binary Search", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Number of Incidents along Corridor (N)", fontsize=11)
    ax.set_ylabel(r"Query Time ($\mu$s)", fontsize=11)
    ax.grid(True, which="both", linestyle="--", alpha=0.5)
    ax.legend(fontsize=11, loc="upper left")

    # Annotate speedup at N = 100,000
    if len(sizes) > 0 and len(lin) > 0 and len(bin_srch) > 0:
        max_speedup = lin[-1] / max(1e-9, bin_srch[-1])
        ax.annotate(
            f"At N = 100,000:\n{max_speedup:.0f}x faster",
            xy=(sizes[-1], bin_srch[-1]),
            xytext=(sizes[-1] * 0.15, bin_srch[-1] * 8),
            arrowprops=dict(facecolor="#2980b9", shrink=0.08, width=1.5, headwidth=6),
            fontsize=10,
            fontweight="bold",
            color="#1b4f72",
            bbox=dict(boxstyle="round,pad=0.4", fc="#ebf5fb", ec="#2980b9", lw=1),
        )

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path))
    plt.close(fig)
    print(f"Saved search benchmark plot to {out_path}")


def plot_pathfinding_benchmark(results: dict, out_path: Path) -> None:
    """Plot Dijkstra vs A* node exploration comparison."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.8), dpi=150)

    d_nodes = results["dijkstra_nodes"]
    a_nodes = results["astar_nodes"]
    pairs_idx = np.arange(1, len(d_nodes) + 1)

    # 1. Node count comparison scatter
    ax1.plot(pairs_idx, d_nodes, "o-", color="#e67e22", alpha=0.85, label="Dijkstra")
    ax1.plot(pairs_idx, a_nodes, "s-", color="#27ae60", alpha=0.85, label="A* (Euclidean $h(n)$)")
    ax1.set_title("Nodes Explored per OD Pair", fontsize=12, fontweight="bold")
    ax1.set_xlabel("Origin-Destination Query Index", fontsize=10)
    ax1.set_ylabel("Explored Node Count", fontsize=10)
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(fontsize=10)

    # 2. Box plot summary
    box_data = [d_nodes, a_nodes]
    bp = ax2.boxplot(
        box_data,
        tick_labels=["Dijkstra", "A* Algorithm"],
        patch_artist=True,
        medianprops=dict(color="black", linewidth=1.5),
    )
    bp["boxes"][0].set_facecolor("#f8c471")
    bp["boxes"][1].set_facecolor("#a9dfbf")

    savings = results.get("reduction_pct", 55.0)
    ax2.set_title(f"A* Search Space Reduction (~{savings:.1f}%)", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Explored Nodes", fontsize=10)
    ax2.grid(True, axis="y", linestyle="--", alpha=0.5)

    plt.suptitle("Pathfinding Benchmark: Dijkstra vs A* on LPU Street Network", fontsize=13, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path))
    plt.close(fig)
    print(f"Saved pathfinding benchmark plot to {out_path}")


def generate_all_benchmarks(save_dir: str = "docs") -> None:
    """Generate both search and pathfinding benchmarks and save plots."""
    out_dir = PROJECT_ROOT / save_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Search Benchmark
    search_res = run_search_benchmark(repeats=300)
    plot_search_benchmark(search_res, out_dir / "benchmark_search.png")

    # 2. Pathfinding Benchmark
    path_res = run_pathfinding_benchmark(num_pairs=40, mode="walk")
    plot_pathfinding_benchmark(path_res, out_dir / "benchmark_dijkstra_astar.png")

    print("\nAll benchmarks successfully generated and saved to docs/!")


if __name__ == "__main__":
    generate_all_benchmarks()
