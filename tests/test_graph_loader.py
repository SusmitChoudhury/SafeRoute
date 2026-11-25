"""
tests/test_graph_loader.py – Unit tests for graph loading and coordinate handling.
"""

from pathlib import Path
import pytest
from core.graph_loader import load_graph, snap_to_node
from config import DEFAULT_START_LATLON, DEFAULT_END_LATLON


def test_cached_files_exist():
    cache_dir = Path("data/cache")
    assert (cache_dir / "graph_walk.graphml").exists()
    assert (cache_dir / "graph_bike.graphml").exists()
    assert (cache_dir / "graph_drive.graphml").exists()
    assert (cache_dir / "basemap.png").exists()
    assert (cache_dir / "basemap_meta.json").exists()


@pytest.mark.parametrize("mode", ["walk", "bike", "drive", "car"])
def test_load_graph(mode):
    G = load_graph(mode)
    assert len(G.nodes) > 100
    assert len(G.edges) > 200

    # Test coordinate integrity on nodes
    sample_node = next(iter(G.nodes.values()))
    assert "x" in sample_node and isinstance(sample_node["x"], float)
    assert "y" in sample_node and isinstance(sample_node["y"], float)
    assert "lat" in sample_node and isinstance(sample_node["lat"], float)
    assert "lon" in sample_node and isinstance(sample_node["lon"], float)

    # In Punjab (LPU), lat is ~31 deg, lon is ~75 deg
    assert 31.0 < sample_node["lat"] < 32.0
    assert 75.0 < sample_node["lon"] < 76.0


def test_snap_to_node():
    G = load_graph("walk")
    node_id, snap_dist = snap_to_node(G, *DEFAULT_START_LATLON)
    assert isinstance(node_id, int)
    assert isinstance(snap_dist, float)
    assert 0 <= snap_dist < 500  # Snap distance should be reasonable

