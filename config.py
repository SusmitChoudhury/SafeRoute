"""
config.py – Every tunable number in one place.

This file is imported by core/, sim/ and ui/ modules.
Change values here to adjust the simulation behaviour
without editing any logic.
"""

# ---------------------------------------------------------------------------
# Map & data download
# ---------------------------------------------------------------------------
CENTER_LATLON = (31.2551, 75.7025)      # Map centre (LPU / Chiheru area)
RADIUS_M = 1500                          # Download radius in metres

# ---------------------------------------------------------------------------
# Routing and look-ahead
# ---------------------------------------------------------------------------
LOOKAHEAD_M = 500.0                      # Detection distance ahead on route (m)
LAMBDA_RISK = 2.0                        # Risk avoidance strength in weight formula
KAPPA_HISTORY = 0.3                      # Chronic-road history weight
BLOCK_RADIUS_M = 40.0                    # Distance (m) within which a blocking incident closes an edge

# ---------------------------------------------------------------------------
# Default start / end points  (approximate – verified against OSM)
# ---------------------------------------------------------------------------
DEFAULT_START_LATLON = (31.2540, 75.7010)   # Law Gate area
DEFAULT_END_LATLON   = (31.2559, 75.7042)   # LPU main area (verified on OSM network)

# ---------------------------------------------------------------------------
# Travel speeds (m/s)
# ---------------------------------------------------------------------------
WALK_SPEED_MPS = 1.39                    # 5 km/h
BIKE_SPEED_MPS = 4.17                    # 15 km/h

# Default car speeds by road class (km/h) when OSM maxspeed tag is missing
CAR_SPEED_DEFAULTS_KMH = {
    "motorway": 80,
    "trunk": 60,
    "primary": 50,
    "secondary": 40,
    "tertiary": 35,
    "residential": 30,
    "service": 15,
    "unclassified": 30,
    "living_street": 10,
}

# ---------------------------------------------------------------------------
# Incident types  (type → default severity, radius, blocking)
# ---------------------------------------------------------------------------
INCIDENT_TYPES = {
    "accident":      {"severity": 4, "radius_m": 150, "blocking": True},
    "flooding":      {"severity": 4, "radius_m": 200, "blocking": True},
    "unsafe_area":   {"severity": 3, "radius_m": 200, "blocking": False},
    "construction":  {"severity": 2, "radius_m": 100, "blocking": True},
    "road_damage":   {"severity": 2, "radius_m": 60,  "blocking": False},
}

# Mode sensitivity multipliers (how much each incident type matters to each mode)
MODE_SENSITIVITY = {
    "accident":      {"walk": 1.0, "bike": 1.0, "car": 1.0},
    "flooding":      {"walk": 0.8, "bike": 1.0, "car": 1.0},
    "unsafe_area":   {"walk": 1.2, "bike": 0.8, "car": 0.3},
    "construction":  {"walk": 0.6, "bike": 0.8, "car": 1.0},
    "road_damage":   {"walk": 0.4, "bike": 1.2, "car": 0.9},
}

# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
TIME_SCALES = (1, 10, 50)               # Simulation speed options
RANDOM_SEED = 42                         # Reproducible demo

# ---------------------------------------------------------------------------
# UI / window
# ---------------------------------------------------------------------------
WINDOW_SIZE = (1600, 900)                # Pygame window size (width, height)
MAP_PANEL_WIDTH_FRAC = 0.65             # Fraction of window width for the map
LOG_RING_BUFFER_SIZE = 500               # Max lines in the live log ring buffer

# ---------------------------------------------------------------------------
# Data-quality thresholds
# ---------------------------------------------------------------------------
SNAP_WARN_M = 50.0                       # Warn if snap distance exceeds this

# ---------------------------------------------------------------------------
# Risk model – age decay
# ---------------------------------------------------------------------------
AGE_DECAY_DAYS = 180                     # Half-life for historical incident decay
PENALTY_FALLBACK_FACTOR = 50             # Multiplier for blocked edges when no path exists

