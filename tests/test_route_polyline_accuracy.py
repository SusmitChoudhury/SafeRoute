"""
tests/test_route_polyline_accuracy.py – Proof for P1: Route Polyline Accuracy.

Verifies:
  1. The drawn polyline incorporates intermediate road curve vertices (not just nodes).
  2. The walker's interpolated position along the route is within 1 m of the drawn polyline
     across 200 sampled distances.
  3. Campus footpaths trigger a clear WARN log when included in the route.
"""

import os
os.environ["MPLCONFIGDIR"] = "cache"
os.environ["SDL_VIDEODRIVER"] = "dummy"

import numpy as np
import pyproj
import pytest
from shapely.geometry import LineString, Point

from core.lookahead import route_polyline, route_to_latlon_polyline
from sim.simulation import Simulation


def test_polyline_contains_intermediate_curve_vertices():
    """Verify that route_to_latlon_polyline contains edge geometry beyond node endpoints."""
    sim = Simulation(mode="walk")
    route = sim.current_route
    assert len(route) >= 2, "Route should contain at least origin and destination"

    dense_polyline = route_to_latlon_polyline(sim.G, route)
    # The default walk route has 8 nodes but 38 dense polyline vertices
    assert len(dense_polyline) > len(route), (
        f"Dense polyline ({len(dense_polyline)} pts) must contain intermediate road curve "
        f"vertices, more than raw node count ({len(route)} nodes)"
    )


def test_walker_position_within_1m_of_drawn_polyline():
    """Sample 200 distances along the route and assert walker position is within 1 m of drawn polyline."""
    sim = Simulation(mode="walk")
    walker = sim.walker
    assert walker is not None, "Walker must be initialized"
    assert walker.total_distance_m > 0, "Route must have positive distance"

    # Get drawn polyline in lat/lon
    drawn_latlon = route_to_latlon_polyline(sim.G, sim.current_route)
    assert len(drawn_latlon) >= 2, "Drawn polyline must have >= 2 points"

    # Convert drawn lat/lon back to UTM to test spatial proximity in metres
    trans_to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
    drawn_lons = [pt[1] for pt in drawn_latlon]
    drawn_lats = [pt[0] for pt in drawn_latlon]
    ux, uy = trans_to_utm.transform(drawn_lons, drawn_lats)
    drawn_line_utm = LineString(np.column_stack([ux, uy]))

    # Sample 200 distances from 0 to total_distance_m
    sample_distances = np.linspace(0.0, walker.total_distance_m, 200)
    max_deviation_m = 0.0

    for s in sample_distances:
        # Interpolate walker position at distance s
        idx = int(np.searchsorted(walker.cum_dist, s))
        if idx == 0:
            wx, wy = walker.points[0]
        elif idx >= len(walker.points):
            wx, wy = walker.points[-1]
        else:
            d0, d1 = walker.cum_dist[idx - 1], walker.cum_dist[idx]
            u = (s - d0) / (d1 - d0) if d1 > d0 else 0.0
            p0, p1 = walker.points[idx - 1], walker.points[idx]
            wx = p0[0] + u * (p1[0] - p0[0])
            wy = p0[1] + u * (p1[1] - p0[1])

        # Distance from walker (wx, wy) in UTM to drawn polyline
        walker_pt = Point(wx, wy)
        dist_m = drawn_line_utm.distance(walker_pt)
        if dist_m > max_deviation_m:
            max_deviation_m = dist_m

        assert dist_m < 1.0, (
            f"Walker at distance {s:.1f} m deviated by {dist_m:.4f} m from drawn polyline "
            f"(must be strictly < 1.0 m)"
        )

    print(f"\n[Proof P1] Maximum deviation across 200 samples: {max_deviation_m:.3e} m (target: < 1.0 m)")


def test_campus_footpaths_warn_logged():
    """Verify that using campus footpaths logs a WARN explaining visibility on tiles."""
    sim = Simulation(mode="walk")
    warn_logs = [
        line for lvl, line in sim.logger.lines()
        if lvl == "WARN" and "campus footpaths" in line
    ]
    assert len(warn_logs) >= 1, f"Expected a WARN log indicating route follows campus footpaths, found: {sim.logger.lines()}"
