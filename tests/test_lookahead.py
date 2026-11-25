"""
tests/test_lookahead.py – Unit tests for look-ahead danger detection and binary query.

Verifies:
  1. Entry distance on a straight synthetic route equals the analytic value.
  2. Tangent circle and non-intersecting circle calculations.
  3. Bisect and linear queries return identical sets for 10,000 random queries.
  4. Look-ahead index construction and query ahead within 500 m.
"""

import math
import random
import numpy as np
import pytest

from core.lookahead import (
    EntryIndex,
    build_entry_index,
    query_ahead,
    route_polyline,
    zone_entry_distance,
)
from core.risk_model import Incident
from config import LOOKAHEAD_M, RANDOM_SEED


def test_analytic_entry_distance_straight_route():
    """Verify entry distance on a straight line matches the exact mathematical solution."""
    # Straight horizontal route from x=0 to x=1000
    points = np.array([[0.0, 0.0], [500.0, 0.0], [1000.0, 0.0]])
    cum = np.array([0.0, 500.0, 1000.0])

    # 1. Incident centred on line at (600, 0) with radius 100
    # Analytic entry: 600 - 100 = 500.0 m
    s_enter = zone_entry_distance(points, cum, centre=(600.0, 0.0), radius=100.0)
    assert s_enter is not None
    assert abs(s_enter - 500.0) < 1e-4

    # 2. Incident tangent to line at (600, 50) with radius 50
    # Touches at (600, 0) -> entry distance 600.0 m
    s_tangent = zone_entry_distance(points, cum, centre=(600.0, 50.0), radius=50.0)
    assert s_tangent is not None
    assert abs(s_tangent - 600.0) < 1e-3

    # 3. Incident far away at (600, 200) with radius 50 (never intersects)
    s_miss = zone_entry_distance(points, cum, centre=(600.0, 200.0), radius=50.0)
    assert s_miss is None


def test_bisect_vs_linear_query_10000_cases():
    """Phase 6 / Unit 5 Requirement:

    Verify that binary search (bisect) and linear scan return identical results
    across 10,000 random query scenarios.
    """
    random.seed(RANDOM_SEED)

    # Synthetic incidents along a 5,000 m route
    num_incidents = 200
    entry_keys = sorted([random.uniform(50.0, 5000.0) for _ in range(num_incidents)])
    entry_ids = list(range(1, num_incidents + 1))

    index = EntryIndex(entry_keys=entry_keys, entry_ids=entry_ids)

    # Linear query baseline implementation
    def linear_query(keys, ids, s_now, horizon):
        limit = s_now + horizon
        return [inc_id for k, inc_id in zip(keys, ids) if s_now <= k <= limit]

    for _ in range(10000):
        s_query = random.uniform(0.0, 5500.0)

        # Binary search query
        binary_hits = query_ahead(index, s_now=s_query, lookahead_m=LOOKAHEAD_M)

        # Linear scan query
        linear_hits = linear_query(entry_keys, entry_ids, s_query, LOOKAHEAD_M)

        assert binary_hits == linear_hits, f"Mismatch at s={s_query}: binary={binary_hits}, linear={linear_hits}"


def test_build_entry_index():
    """Verify EntryIndex builds sorted keys for multiple incidents."""
    points = np.array([[0.0, 0.0], [1000.0, 0.0]])
    cum = np.array([0.0, 1000.0])

    incidents = [
        Incident(id=1, type="accident", x=800.0, y=0.0, severity=4, radius_m=100.0, blocking=True),  # enters at 700
        Incident(id=2, type="flooding", x=400.0, y=0.0, severity=4, radius_m=100.0, blocking=True),  # enters at 300
        Incident(id=3, type="unsafe_area", x=600.0, y=500.0, severity=3, radius_m=50.0, blocking=False), # misses
    ]

    index = build_entry_index(points, cum, incidents)
    assert len(index.entry_keys) == 2
    # Must be sorted
    assert index.entry_keys[0] < index.entry_keys[1]
    assert abs(index.entry_keys[0] - 300.0) < 1e-4
    assert abs(index.entry_keys[1] - 700.0) < 1e-4
    assert index.entry_ids == [2, 1]
