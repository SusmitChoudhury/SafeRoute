"""
core/lookahead.py – Route polyline, zone-entry distance, and binary search look-ahead index.

Implements the 500 m detection rule from Section 6.7 of the build plan:
  1. Entry distance of an incident: Solves the line-circle intersection
     |A + u(B - A) - c|^2 = R^2 for u in [0, 1] on each polyline segment.
  2. Index: Collects (s_enter, incident_id) for incidents touching the route,
     sorted by s_enter.
  3. Query on every tick: Uses bisect_left to find incidents within s_now + 500 m
     in O(log I + k) time.
  4. Hysteresis: Each incident triggers Warning 1 at most once per route.
"""

import bisect
from dataclasses import dataclass
import math
from typing import Optional

import networkx as nx
import numpy as np
import pyproj
from shapely.geometry import LineString

from config import LOOKAHEAD_M
from core.risk_model import Incident


@dataclass
class EntryIndex:
    """Pre-computed, sorted look-ahead index for a specific route."""
    entry_keys: list[float]  # Cumulative distance (m) where route enters danger zone
    entry_ids: list[int]     # Incident IDs corresponding to entry_keys


def route_polyline(G: nx.MultiDiGraph, path: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Convert a graph path (node list) into UTM points and cumulative distances.

    Args:
        G: Projected NetworkX MultiDiGraph (in UTM metres).
        path: List of node IDs along the route.

    Returns:
        tuple[np.ndarray, np.ndarray]:
            - points: (N, 2) array of UTM coordinates [[x0, y0], [x1, y1], ...]
            - cum_dist: (N,) array of cumulative distances along the polyline in metres
    """
    if not path:
        return np.empty((0, 2), dtype=float), np.empty(0, dtype=float)

    pts = []
    # Start node
    s = path[0]
    pts.append((float(G.nodes[s]["x"]), float(G.nodes[s]["y"])))

    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        if not G.has_edge(u, v):
            vx, vy = float(G.nodes[v]["x"]), float(G.nodes[v]["y"])
            pts.append((vx, vy))
            continue

        best_edge_data = min(
            G[u][v].values(),
            key=lambda d: float(d.get("length", 1.0)),
        )

        if "geometry" in best_edge_data and isinstance(best_edge_data["geometry"], LineString):
            coords = list(best_edge_data["geometry"].coords)
            # Ensure correct direction u -> v
            d_first = math.hypot(coords[0][0] - G.nodes[u]["x"], coords[0][1] - G.nodes[u]["y"])
            d_last = math.hypot(coords[-1][0] - G.nodes[u]["x"], coords[-1][1] - G.nodes[u]["y"])
            if d_last < d_first:
                coords.reverse()
            for pt in coords[1:]:
                pts.append((float(pt[0]), float(pt[1])))
        else:
            vx, vy = float(G.nodes[v]["x"]), float(G.nodes[v]["y"])
            pts.append((vx, vy))

    pts_arr = np.array(pts, dtype=float)

    # Compute cumulative distances
    if len(pts_arr) <= 1:
        cum_arr = np.zeros(len(pts_arr), dtype=float)
    else:
        diffs = np.diff(pts_arr, axis=0)
        segment_lengths = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_arr = np.concatenate(([0.0], np.cumsum(segment_lengths)))

    return pts_arr, cum_arr


def zone_entry_distance(
    points: np.ndarray,
    cum: np.ndarray,
    centre: tuple[float, float],
    radius: float,
) -> Optional[float]:
    """Find the exact cumulative distance s_enter at which the route enters a circle.

    Solves the line-circle quadratic equation:
      |A + u(B - A) - c|^2 = R^2  for u in [0, 1]

    Args:
        points: (N, 2) array of polyline vertices in UTM coordinates.
        cum: (N,) array of cumulative distances.
        centre: (cx, cy) circle centre in UTM coordinates.
        radius: Circle radius in metres.

    Returns:
        float | None: Smallest cumulative distance s_enter, or None if no intersection.
    """
    if len(points) < 2:
        return None

    cx, cy = centre
    R_sq = radius * radius

    # Vectorized computation across all segments
    A = points[:-1]            # Segment start points (M, 2)
    B = points[1:]             # Segment end points (M, 2)
    V = B - A                  # Segment direction vectors (M, 2)
    D = A - np.array([cx, cy]) # Vector from circle centre to A (M, 2)

    # Quadratic coefficients: a*u^2 + b*u + c = 0
    a = V[:, 0]**2 + V[:, 1]**2
    b = 2.0 * (D[:, 0] * V[:, 0] + D[:, 1] * V[:, 1])
    c_const = D[:, 0]**2 + D[:, 1]**2 - R_sq

    # Segment length squared
    seg_lens = np.hypot(V[:, 0], V[:, 1])

    # Check segments sequentially to find the earliest entry
    for i in range(len(A)):
        a_i = a[i]
        b_i = b[i]
        c_i = c_const[i]
        L_i = seg_lens[i]
        d_start = cum[i]

        if a_i < 1e-12:
            continue

        # Check if segment start A is already inside the danger zone
        if c_i <= 0.0:
            return float(d_start)

        # Discriminant
        discriminant = b_i * b_i - 4.0 * a_i * c_i
        if discriminant < 0.0:
            continue

        sqrt_disc = math.sqrt(discriminant)
        u1 = (-b_i - sqrt_disc) / (2.0 * a_i)

        # Smallest positive intersection root
        if 0.0 <= u1 <= 1.0:
            return float(d_start + u1 * L_i)

        u2 = (-b_i + sqrt_disc) / (2.0 * a_i)
        if 0.0 <= u2 <= 1.0:
            return float(d_start + u2 * L_i)

    return None


def build_entry_index(
    points: np.ndarray,
    cum: np.ndarray,
    incidents: list[Incident],
) -> EntryIndex:
    """Construct the sorted look-ahead index for a route.

    Only active live hazards (source != 'historical') are indexed for
    emergency look-ahead alarms; historical incidents inform chronic risk only.

    Args:
        points: (N, 2) route points.
        cum: (N,) cumulative distances.
        incidents: List of active Incident objects.

    Returns:
        EntryIndex: Sorted entry distances and corresponding incident IDs.
    """
    entries = []

    for inc in incidents:
        if not inc.active or inc.source == "historical":
            continue
        s_enter = zone_entry_distance(points, cum, (inc.x, inc.y), inc.radius_m)
        if s_enter is not None:
            entries.append((s_enter, inc.id))

    # Sort primarily by entry distance s_enter
    entries.sort(key=lambda item: item[0])

    keys = [item[0] for item in entries]
    ids = [item[1] for item in entries]
    return EntryIndex(entry_keys=keys, entry_ids=ids)


def query_ahead(
    index: EntryIndex,
    s_now: float,
    lookahead_m: float = LOOKAHEAD_M,
) -> list[int]:
    """Query the look-ahead index using binary search (bisect).

    Runs in O(log I + k) time.

    Args:
        index: Pre-computed EntryIndex.
        s_now: Current traveller distance along route in metres.
        lookahead_m: Look-ahead horizon in metres (default from config: 500 m).

    Returns:
        list[int]: List of incident IDs entering the route within (s_now, s_now + lookahead_m].
    """
    if not index.entry_keys:
        return []

    # Find earliest incident ahead of the walker
    lo = bisect.bisect_left(index.entry_keys, s_now)
    limit = s_now + lookahead_m

    hits = []
    while lo < len(index.entry_keys) and index.entry_keys[lo] <= limit:
        hits.append(index.entry_ids[lo])
        lo += 1

    return hits


_TRANSFORMER_UTM_TO_LATLON = pyproj.Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)


def route_to_latlon_polyline(
    G: nx.MultiDiGraph,
    path: list[int],
    graph_crs: str = "EPSG:32643",
) -> list[list[float]]:
    """Convert a graph route to a dense list of [lat, lon] coordinates including all intermediate edge curves.

    Uses pyproj with vectorised transformation for instant sub-millisecond execution.
    Returned format is [[lat0, lon0], [lat1, lon1], ...] matching Leaflet / map conventions.
    """
    if not path or not G:
        return []
    pts, _ = route_polyline(G, path)
    if len(pts) == 0:
        return []

    if graph_crs == "EPSG:32643":
        transformer = _TRANSFORMER_UTM_TO_LATLON
    else:
        transformer = pyproj.Transformer.from_crs(graph_crs, "EPSG:4326", always_xy=True)

    lons, lats = transformer.transform(pts[:, 0], pts[:, 1])
    return [[float(lat), float(lon)] for lat, lon in zip(lats, lons)]

