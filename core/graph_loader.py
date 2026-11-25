"""
core/graph_loader.py – Download, cache, and load OSM street graphs.

Provides functions to load walk/bike/drive graphs from cached GraphML files
and snap lat/lon points to the nearest graph node in UTM coordinates.

Coordinates:
  - Input coordinates are WGS84 latitude and longitude (EPSG:4326, in degrees).
  - Graph calculations are strictly performed in projected UTM coordinates (in metres).
"""

import logging
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox
import pyproj

from config import SNAP_WARN_M

logger = logging.getLogger(__name__)

# Base cache directory relative to project root
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

# Transformer cache: (from_crs, to_crs) -> pyproj.Transformer
_TRANSFORMERS: dict[tuple[str, str], pyproj.Transformer] = {}


def _get_transformer(from_crs: str, to_crs: str) -> pyproj.Transformer:
    """Retrieve or create a cached pyproj Transformer."""
    key = (str(from_crs), str(to_crs))
    if key not in _TRANSFORMERS:
        _TRANSFORMERS[key] = pyproj.Transformer.from_crs(from_crs, to_crs, always_xy=True)
    return _TRANSFORMERS[key]


def load_graph(mode: str) -> nx.MultiDiGraph:
    """Load a projected UTM street graph from the local cache.

    Args:
        mode: Travel mode ('walk', 'bike', 'drive', or 'car').
              'car' is an alias for 'drive'.

    Returns:
        nx.MultiDiGraph: Projected graph with node coordinates in UTM (x, y in metres)
        and original coordinates preserved (lat, lon in degrees).

    Raises:
        FileNotFoundError: If the cached GraphML file does not exist.
                           Run tools/prepare_data.py first.
    """
    normalized_mode = "drive" if mode.lower() in ("car", "drive") else mode.lower()
    filepath = CACHE_DIR / f"graph_{normalized_mode}.graphml"

    if not filepath.exists():
        raise FileNotFoundError(
            f"Cached graph for '{mode}' not found at {filepath}.\n"
            f"Please run 'python tools/prepare_data.py' first to download and cache the data."
        )

    # Load graph using OSMnx
    G: nx.MultiDiGraph = ox.load_graphml(filepath=filepath)

    # Ensure node coordinates are strongly typed floats
    for _, data in G.nodes(data=True):
        data["x"] = float(data["x"])
        data["y"] = float(data["y"])
        if "lat" in data:
            data["lat"] = float(data["lat"])
        elif "y_original" in data:
            data["lat"] = float(data["y_original"])
        else:
            data["lat"] = float(data["y"])

        if "lon" in data:
            data["lon"] = float(data["lon"])
        elif "x_original" in data:
            data["lon"] = float(data["x_original"])
        else:
            data["lon"] = float(data["x"])

    # Ensure edge lengths are typed floats
    for _, _, _, data in G.edges(keys=True, data=True):
        if "length" in data:
            data["length"] = float(data["length"])

    return G


def snap_to_node(G: nx.MultiDiGraph, lat: float, lon: float) -> tuple[int, float]:
    """Snap a WGS84 (lat, lon) coordinate to the nearest node in the projected graph.

    Args:
        G: Projected NetworkX MultiDiGraph (in UTM).
        lat: Latitude in degrees (WGS84).
        lon: Longitude in degrees (WGS84).

    Returns:
        tuple[int, float]: (node_id, snap_distance_in_metres)
    """
    graph_crs = G.graph.get("crs", "EPSG:32643")
    transformer = _get_transformer("EPSG:4326", graph_crs)

    # Transform (lon, lat) to UTM (x, y) in metres
    utm_x, utm_y = transformer.transform(lon, lat)

    # Find nearest node and Euclidean distance in metres
    nearest_node, snap_dist_m = ox.nearest_nodes(G, utm_x, utm_y, return_dist=True)

    # Check for excessive snap distance (data quality rule Section 5.3)
    if snap_dist_m > SNAP_WARN_M:
        logger.warning(f"snap distance {snap_dist_m:.1f} m - check OSM coverage here")

    return int(nearest_node), float(snap_dist_m)
