"""
tests/test_travel_model.py – Unit tests for travel-time model and walker motion.

Verifies:
  1. 1,000 m takes ~720 s walking (1.39 m/s) and ~240 s biking (4.17 m/s).
  2. add_travel_times assigns valid speed_mps and base_time to all edges.
  3. Walker advances at exactly mode speed (1.39 m/s for walk) along the polyline.
  4. SimLogger ring buffer and file sink operation.
"""

from pathlib import Path
import pytest

from config import WALK_SPEED_MPS, BIKE_SPEED_MPS
from core.graph_loader import load_graph
from core.travel_model import (
    add_travel_times,
    calculate_route_stats,
    MODE_SPEED_MPS,
)
from sim.logger import SimLogger
from sim.walker import Walker


def test_walking_and_biking_time_1000m():
    """Phase 5 requirement: 1,000 m takes 720 s walking and 240 s biking."""
    dist_m = 1000.0

    walk_time = dist_m / WALK_SPEED_MPS
    bike_time = dist_m / BIKE_SPEED_MPS

    # Walking: 1000 / 1.39 = 719.42 s (~720 s)
    assert abs(walk_time - 720.0) < 2.0, f"Walking 1000m should be ~720s, got {walk_time}"

    # Biking: 1000 / 4.17 = 239.81 s (~240 s)
    assert abs(bike_time - 240.0) < 2.0, f"Biking 1000m should be ~240s, got {bike_time}"


def test_add_travel_times_all_edges():
    """Verify speed_mps and base_time are assigned to every edge."""
    for mode in ["walk", "bike", "car"]:
        G = load_graph(mode)
        stats = add_travel_times(G, mode)
        assert stats["total_edges"] > 0
        assert stats["total_edges"] == len(G.edges)

        # Check edge attributes
        for u, v, k, data in G.edges(keys=True, data=True):
            assert "speed_mps" in data and data["speed_mps"] > 0
            assert "base_time" in data and data["base_time"] > 0
            # base_time = length / speed
            expected = float(data["length"]) / data["speed_mps"]
            assert abs(data["base_time"] - expected) < 1e-4


def test_walker_motion():
    """Verify walker moves along the polyline at 1.39 m/s."""
    G = load_graph("walk")
    nodes = list(G.nodes)[:10]

    walker = Walker(G, nodes, speed_mps=1.39)
    assert walker.distance_travelled == 0.0
    assert not walker.is_finished

    # Step by 10 simulation seconds
    walker.update(sim_dt=10.0)
    expected_dist = 1.39 * 10.0
    assert abs(walker.distance_travelled - expected_dist) < 1e-3
    assert walker.lat != 0.0
    assert walker.lon != 0.0


def test_sim_logger_ring_buffer_and_file(tmp_path):
    """Verify logger ring buffer formatting and file persistence."""
    logger = SimLogger(log_dir=tmp_path)
    line = logger.log("INFO", "test_mod", "Hello test", sim_time=75.5)

    # Expected timestamp [01:15.5]
    assert "[01:15.5]" in line
    assert "INFO" in line
    assert "test_mod" in line
    assert "Hello test" in line

    # Check ring buffer
    lines = logger.lines()
    assert len(lines) == 1
    assert lines[0][0] == "INFO"

    # Check log file exists and contains line
    assert logger.log_file.exists()
    content = logger.log_file.read_text(encoding="utf-8")
    assert "Hello test" in content
