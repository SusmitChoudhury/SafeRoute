"""
core/risk_model.py – Rule-based risk scoring and edge weight computation.

Implements the transparent risk formula from Section 6.4 of the build plan:
  d_ei = shortest distance from edge e to incident centre c_i (metres)
  f    = max(0, 1 - d_ei / R_i)
  r_e  = sum_i( s_i * m(type_i, mode) * f * age_factor_i )
  r_e  = r_e + kappa * ln(1 + accidents_on_edge)
  w_e  = base_time_e * (1 + lambda * r_e)
  w_e  = infinity if blocking incident within 40 m (car / vehicle mode)

No machine learning is used – this is purely rule-based and explainable.
"""

from dataclasses import dataclass
import math
from typing import Callable, Optional

import networkx as nx
import pyproj
from shapely.geometry import LineString, Point

from config import (
    AGE_DECAY_DAYS,
    BLOCK_RADIUS_M,
    INCIDENT_TYPES,
    KAPPA_HISTORY,
    LAMBDA_RISK,
    MODE_SENSITIVITY,
    PENALTY_FALLBACK_FACTOR,
    WALK_SPEED_MPS,
    BIKE_SPEED_MPS,
    CAR_SPEED_DEFAULTS_KMH,
)


@dataclass
class Incident:
    """Incident entity used by the risk and simulation models."""
    id: int
    type: str
    x: float             # UTM Easting (metres)
    y: float             # UTM Northing (metres)
    severity: int        # 1 to 5
    radius_m: float      # Zone radius in metres
    blocking: bool       # Whether it closes the road for vehicles
    age_days: float = 0.0  # Elapsed days (for historical decay)
    lat: float = 0.0     # WGS84 Latitude
    lon: float = 0.0     # WGS84 Longitude
    source: str = "live" # 'historical', 'live', or 'simulated'
    active: bool = True


def get_edge_geometry(G: nx.MultiDiGraph, u: int, v: int, k: int) -> LineString:
    """Retrieve or construct the Shapely LineString geometry of an edge in UTM."""
    edge_data = G[u][v][k]
    cached = edge_data.get("_cached_geom")
    if cached is not None:
        return cached

    if "geometry" in edge_data and isinstance(edge_data["geometry"], LineString):
        edge_data["_cached_geom"] = edge_data["geometry"]
        return edge_data["geometry"]

    # Build straight line between node UTM coordinates
    u_data = G.nodes[u]
    v_data = G.nodes[v]
    geom = LineString([(u_data["x"], u_data["y"]), (v_data["x"], v_data["y"])])
    edge_data["_cached_geom"] = geom
    return geom


def compute_edge_risk(G: nx.MultiDiGraph, incidents: list[Incident], mode: str) -> dict[tuple[int, int, int], float]:
    """Calculate the danger risk score r_e for every edge in the graph.

    Formula:
      r_e = sum over i of [ s_i * m(type_i, mode) * f * age_factor_i ]
            + kappa * ln(1 + accidents_on_edge)

    Args:
        G: Projected NetworkX MultiDiGraph (in UTM).
        incidents: List of active Incident objects.
        mode: Travel mode ('walk', 'bike', 'car', or 'drive').

    Returns:
        dict: Mapping of (u, v, key) -> r_e (risk score >= 0.0).
    """
    normalized_mode = "car" if mode in ("car", "drive") else mode
    edge_risks: dict[tuple[int, int, int], float] = {}

    if not incidents:
        for u, v, k in G.edges(keys=True):
            edge_risks[(u, v, k)] = 0.0
        return edge_risks

    # Pre-build Shapely Points and attributes for active incidents
    active_incidents = [inc for inc in incidents if inc.active]
    incident_data = []
    for inc in active_incidents:
        pt = Point(inc.x, inc.y)
        # Mode sensitivity multiplier
        m_mode = MODE_SENSITIVITY.get(inc.type, {}).get(normalized_mode, 1.0)
        # Age decay factor: 1.0 for live incidents, exponential decay for historical
        if inc.source == "live":
            age_factor = 1.0
        else:
            age_factor = math.exp(-inc.age_days / AGE_DECAY_DAYS)

        is_accident = (inc.type == "accident")
        incident_data.append((inc, pt, m_mode, age_factor, is_accident))

    for u, v, k in G.edges(keys=True):
        geom = get_edge_geometry(G, u, v, k)
        r_e = 0.0
        accidents_on_edge = 0

        for inc, pt, m_mode, age_factor, is_accident in incident_data:
            d_ei = geom.distance(pt)
            if d_ei <= inc.radius_m:
                # Linear falloff: 1 at centre, 0 at perimeter
                f = 1.0 - (d_ei / inc.radius_m)
                r_e += inc.severity * m_mode * f * age_factor

            # Chronic accident tracking: count accidents within 40m of the edge
            if is_accident and d_ei <= BLOCK_RADIUS_M:
                accidents_on_edge += 1

        # Chronic accident hotspot logarithmic term
        if accidents_on_edge > 0:
            r_e += KAPPA_HISTORY * math.log(1.0 + accidents_on_edge)

        edge_risks[(u, v, k)] = max(0.0, r_e)

    return edge_risks


def _get_base_travel_time(G: nx.MultiDiGraph, u: int, v: int, k: int, mode: str) -> float:
    """Retrieve or compute the base travel time of an edge in seconds."""
    data = G[u][v][k]
    if "base_time" in data:
        return float(data["base_time"])
    if "travel_time" in data:
        return float(data["travel_time"])

    length = float(data.get("length", 1.0))
    normalized_mode = "car" if mode in ("car", "drive") else mode

    if normalized_mode == "walk":
        speed = WALK_SPEED_MPS
    elif normalized_mode == "bike":
        speed = BIKE_SPEED_MPS
    else:
        # Car mode: check maxspeed, else fallback to highway class
        if "maxspeed" in data:
            try:
                ms = data["maxspeed"]
                if isinstance(ms, list):
                    ms = ms[0]
                speed_kmh = float(str(ms).split()[0])
                speed = speed_kmh / 3.6
            except Exception:
                speed = 30.0 / 3.6
        else:
            hw = data.get("highway", "residential")
            if isinstance(hw, list):
                hw = hw[0]
            speed_kmh = CAR_SPEED_DEFAULTS_KMH.get(hw, 30.0)
            speed = speed_kmh / 3.6

    return max(0.1, length / speed)


def make_weight_fn(
    G: nx.MultiDiGraph,
    risk: dict[tuple[int, int, int], float],
    mode: str,
    incidents: list[Incident],
    lam: float = LAMBDA_RISK,
    fallback: bool = False,
) -> Callable[[int, int, int], float]:
    """Create a weight function for Dijkstra/A* routing.

    Formula:
      w_e = base_time_e * (1 + lambda * r_e)
      w_e = infinity if blocking incident within 40 m (vehicles only: car, drive)

    Fallback Mode:
      If blocked roads make the destination unreachable, fallback=True applies
      a 50x penalty multiplier instead of infinity, allowing the least-risk path.

    Args:
        G: Projected NetworkX MultiDiGraph.
        risk: Pre-calculated edge risks from compute_edge_risk.
        mode: Travel mode ('walk', 'bike', 'car', or 'drive').
        incidents: Active Incident objects.
        lam: Risk multiplier lambda (default from config.py: 2.0).
        fallback: If True, uses penalty factor instead of infinity for blocked edges.

    Returns:
        Callable[[int, int, int], float]: Edge weight in seconds (or inf).
    """
    normalized_mode = "car" if mode in ("car", "drive") else mode
    is_vehicle = normalized_mode == "car"

    # Pre-identify edges within BLOCK_RADIUS_M of a blocking incident
    blocked_edges: set[tuple[int, int, int]] = set()
    if is_vehicle and incidents:
        blocking_pts = [Point(inc.x, inc.y) for inc in incidents if inc.active and inc.blocking]
        if blocking_pts:
            for u, v, k in G.edges(keys=True):
                geom = get_edge_geometry(G, u, v, k)
                for pt in blocking_pts:
                    if geom.distance(pt) <= BLOCK_RADIUS_M:
                        blocked_edges.add((u, v, k))
                        break

    def weight_function(u: int, v: int, k: int) -> float:
        base_time = _get_base_travel_time(G, u, v, k, mode)
        r_e = risk.get((u, v, k), 0.0)

        # Check vehicle blocking
        if (u, v, k) in blocked_edges:
            if fallback:
                # Fallback: 50x penalty factor
                return base_time * (1.0 + lam * r_e) * PENALTY_FALLBACK_FACTOR
            return math.inf

        return base_time * (1.0 + lam * r_e)

    return weight_function
