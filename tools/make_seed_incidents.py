"""
tools/make_seed_incidents.py – Generates simulated incidents on real street edges.

Picks random edges from the walk graph (seeded random, seed 42), places
historical incidents at each edge's midpoint so every incident lies on a real road,
and writes data/incidents_seed.csv.

Real-life history demonstration:
  Multiple accidents are deliberately placed on the same road segment to activate
  the chronic history term: kappa * ln(1 + accidents_on_edge).
"""

import csv
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import DEFAULT_START_LATLON, DEFAULT_END_LATLON, INCIDENT_TYPES, RANDOM_SEED
from core.graph_loader import load_graph

SEED_CSV_PATH = PROJECT_ROOT / "data" / "incidents_seed.csv"


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Euclidean approximation of distance in metres."""
    d_lat = (lat1 - lat2) * 111320.0
    d_lon = (lon1 - lon2) * 111320.0 * math.cos(math.radians(lat1))
    return math.hypot(d_lat, d_lon)


def generate_seed_incidents(num_incidents: int = 10) -> list[dict]:
    """Generate reproducible simulated incidents sitting on real road edges.

    P7 Acceptance Criteria:
      - At most 12 simulated incidents.
      - Radius between 60 m and 120 m.
      - None within 120 m of default START or END markers.

    Args:
        num_incidents: Number of incidents to generate (default 10).

    Returns:
        list[dict]: List of incident records.
    """
    random.seed(RANDOM_SEED)

    G = load_graph("walk")
    edges = list(G.edges(keys=True, data=True))
    if not edges:
        raise ValueError("Walk graph has no edges!")

    start_lat, start_lon = DEFAULT_START_LATLON
    end_lat, end_lon = DEFAULT_END_LATLON

    # Filter candidate edges that are >120 m away from default endpoints
    valid_candidates = []
    for u, v, k, data in edges:
        u_node = G.nodes[u]
        v_node = G.nodes[v]
        mid_lat = (u_node["lat"] + v_node["lat"]) / 2.0
        mid_lon = (u_node["lon"] + v_node["lon"]) / 2.0
        if _dist_m(mid_lat, mid_lon, start_lat, start_lon) >= 120.0 and _dist_m(mid_lat, mid_lon, end_lat, end_lon) >= 120.0:
            valid_candidates.append((u, v, k, mid_lat, mid_lon))

    if len(valid_candidates) < num_incidents:
        chosen = valid_candidates
    else:
        chosen = random.sample(valid_candidates, num_incidents)

    incidents = []
    types_list = list(INCIDENT_TYPES.keys())
    now = datetime.now()

    for idx, (u, v, k, mid_lat, mid_lon) in enumerate(chosen):
        if idx == 0:
            # Chronic hotspot demonstration (2 historical accidents on same edge)
            for sub_i in range(2):
                inc_type = "accident"
                conf = INCIDENT_TYPES[inc_type]
                days_ago = random.randint(15, 120)
                created_at = (now - timedelta(days=days_ago)).isoformat()
                radius = max(60, min(120, conf["radius_m"]))
                incidents.append({
                    "type": inc_type,
                    "lat": round(mid_lat, 6),
                    "lon": round(mid_lon, 6),
                    "severity": conf["severity"],
                    "radius_m": radius,
                    "blocking": 1 if conf["blocking"] else 0,
                    "source": "historical",
                    "created_at": created_at,
                    "active": 1,
                })
        else:
            inc_type = types_list[idx % len(types_list)]
            conf = INCIDENT_TYPES[inc_type]
            days_ago = random.randint(5, 180)
            created_at = (now - timedelta(days=days_ago)).isoformat()
            radius = max(60, min(120, conf["radius_m"]))
            incidents.append({
                "type": inc_type,
                "lat": round(mid_lat, 6),
                "lon": round(mid_lon, 6),
                "severity": conf["severity"],
                "radius_m": radius,
                "blocking": 1 if conf["blocking"] else 0,
                "source": "historical",
                "created_at": created_at,
                "active": 1,
            })

    return incidents


def main():
    print(f"Generating seed incidents with seed={RANDOM_SEED}...")
    incidents = generate_seed_incidents()

    SEED_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SEED_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["type", "lat", "lon", "severity", "radius_m", "blocking", "source", "created_at", "active"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(incidents)

    print(f"Saved {len(incidents)} seed incidents to {SEED_CSV_PATH}")


if __name__ == "__main__":
    main()
