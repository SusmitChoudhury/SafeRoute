"""
core/travel_model.py – Speed assignments and edge travel times.

Assigns speed_mps and base_time (seconds) to every edge in the graph
based on the travel mode (walk, bike, car):
  Walk: 5 km/h = 1.39 m/s (walk graph)
  Bike: 15 km/h = 4.17 m/s (bike graph)
  Car: OSM maxspeed if present, else default by road class (drive graph)

Formulas:
  base_time(edge) = length(edge) / speed(edge)  # seconds
  ETA(route)      = sum of base_time over the route's edges
"""

import math
from typing import Optional
import networkx as nx

from config import (
    CAR_SPEED_DEFAULTS_KMH,
    WALK_SPEED_MPS,
    BIKE_SPEED_MPS,
)

MODE_SPEED_MPS = {
    "walk": WALK_SPEED_MPS,
    "bike": BIKE_SPEED_MPS,
}


def parse_maxspeed_kmh(raw_val) -> Optional[float]:
    """Parse OSM maxspeed tag value into km/h float.

    Handles '50', '30 km/h', '20 mph', list of values, etc.
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, list):
        raw_val = raw_val[0] if raw_val else None
        if raw_val is None:
            return None

    val_str = str(raw_val).strip().lower()
    try:
        if "mph" in val_str:
            num = float(val_str.replace("mph", "").strip())
            return num * 1.60934
        if "km/h" in val_str or "kph" in val_str:
            num = float(val_str.replace("km/h", "").replace("kph", "").strip())
            return num
        return float(val_str)
    except (ValueError, TypeError):
        return None


def add_travel_times(G: nx.MultiDiGraph, mode: str) -> dict[str, int]:
    """Assign speed_mps and base_time (seconds) to every edge in G.

    Args:
        G: Projected NetworkX MultiDiGraph.
        mode: 'walk', 'bike', 'car', or 'drive'.

    Returns:
        dict: {"assumed_speed_edges": n, "total_edges": m}
    """
    normalized_mode = "car" if mode.lower() in ("car", "drive") else mode.lower()
    assumed_speed_edges = 0
    total_edges = 0

    for u, v, k, data in G.edges(keys=True, data=True):
        total_edges += 1
        length = float(data.get("length", 1.0))

        if normalized_mode == "walk":
            speed_mps = MODE_SPEED_MPS["walk"]
        elif normalized_mode == "bike":
            speed_mps = MODE_SPEED_MPS["bike"]
        else:
            # Car mode: check maxspeed tag
            parsed_kmh = parse_maxspeed_kmh(data.get("maxspeed"))
            if parsed_kmh is not None and parsed_kmh > 0:
                speed_mps = parsed_kmh / 3.6
            else:
                assumed_speed_edges += 1
                hw = data.get("highway", "residential")
                if isinstance(hw, list):
                    hw = hw[0] if hw else "residential"
                speed_kmh = CAR_SPEED_DEFAULTS_KMH.get(hw, 30.0)
                speed_mps = speed_kmh / 3.6

        # Avoid division by zero
        speed_mps = max(0.1, speed_mps)
        base_time = max(0.01, length / speed_mps)

        data["speed_mps"] = speed_mps
        data["base_time"] = base_time

    return {"assumed_speed_edges": assumed_speed_edges, "total_edges": total_edges}


def calculate_route_stats(G: nx.MultiDiGraph, path: list[int], mode: str) -> dict[str, float]:
    """Compute total length (metres) and ETA (seconds) along a sequence of nodes.

    Args:
        G: Graph containing node sequence.
        path: List of node IDs.
        mode: Travel mode.

    Returns:
        dict: {"length_m": float, "eta_seconds": float, "eta_minutes": float}
    """
    if len(path) < 2:
        return {"length_m": 0.0, "eta_seconds": 0.0, "eta_minutes": 0.0}

    total_len = 0.0
    total_time = 0.0

    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        if not G.has_edge(u, v):
            continue

        # If parallel edges exist, pick the edge with shortest base_time / length
        best_time = math.inf
        best_len = 0.0
        for k, edge_data in G[u][v].items():
            t = edge_data.get("base_time")
            l = float(edge_data.get("length", 1.0))
            if t is None:
                # Compute on the fly if not set
                if mode == "walk":
                    t = l / WALK_SPEED_MPS
                elif mode == "bike":
                    t = l / BIKE_SPEED_MPS
                else:
                    t = l / (30.0 / 3.6)
            if t < best_time:
                best_time = t
                best_len = l

        total_time += best_time
        total_len += best_len

    return {
        "length_m": total_len,
        "eta_seconds": total_time,
        "eta_minutes": total_time / 60.0,
    }
