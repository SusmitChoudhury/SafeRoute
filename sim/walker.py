"""
sim/walker.py – Traveller animation along the route polyline.

Features:
  - Uses binary search (bisect) on cumulative segment distances for O(log n)
    position lookup per tick.
  - Computes direction heading angle for realistic directional indicator.
  - Identifies the next node ahead on the current edge for clean reroute splicing.
  - Supports variable travel speeds based on mode (walk, bike, car).
"""

import bisect
import math
from typing import Optional

import networkx as nx
import pyproj
from shapely.geometry import LineString


class Walker:
    """Simulates a traveller moving along a graph route."""

    def __init__(
        self,
        G: nx.MultiDiGraph,
        path: list[int],
        speed_mps: float = 1.39,
        graph_crs: str = "EPSG:32643",
    ):
        """Initialize the walker along a node path.

        Args:
            G: Projected NetworkX MultiDiGraph (in UTM metres).
            path: List of graph node IDs from origin to destination.
            speed_mps: Travel speed in metres per second (default 1.39 m/s for walk).
            graph_crs: CRS string of G for inverse coordinate transformation.
        """
        self.G = G
        self.path = list(path)
        self.speed_mps = float(speed_mps)
        self.graph_crs = graph_crs

        # Transformer to convert UTM (x, y) -> WGS84 (lat, lon)
        self.transformer_to_latlon = pyproj.Transformer.from_crs(
            graph_crs, "EPSG:4326", always_xy=True
        )

        # Polylines and cumulative distances
        self.points: list[tuple[float, float]] = []
        self.cum_dist: list[float] = []
        self.segment_target_node: list[int] = []
        self.total_distance_m: float = 0.0

        # Motion state
        self.distance_travelled: float = 0.0
        self.x: float = 0.0
        self.y: float = 0.0
        self.lat: float = 0.0
        self.lon: float = 0.0
        self.heading_deg: float = 0.0
        self.next_node_ahead: Optional[int] = None
        self.is_finished: bool = False
        self.manual_mode: bool = False
        self.current_node: int = path[0] if path else 0

        self._build_polyline()

    def _build_polyline(self) -> None:
        """Construct the piecewise linear polyline and cumulative distance array."""
        self.points = []
        self.cum_dist = []
        self.segment_target_node = []

        if not self.path:
            self.total_distance_m = 0.0
            self.is_finished = True
            return

        # Starting node
        start_node = self.path[0]
        start_x = float(self.G.nodes[start_node]["x"])
        start_y = float(self.G.nodes[start_node]["y"])
        self.points.append((start_x, start_y))
        self.cum_dist.append(0.0)

        accumulated = 0.0

        for i in range(len(self.path) - 1):
            u = self.path[i]
            v = self.path[i + 1]

            if not self.G.has_edge(u, v):
                # Fallback to straight segment between nodes
                vx = float(self.G.nodes[v]["x"])
                vy = float(self.G.nodes[v]["y"])
                prev_x, prev_y = self.points[-1]
                step_len = math.hypot(vx - prev_x, vy - prev_y)
                accumulated += step_len
                self.points.append((vx, vy))
                self.cum_dist.append(accumulated)
                self.segment_target_node.append(v)
                continue

            # Pick the edge with smallest length among multi-edges
            best_edge_data = min(
                self.G[u][v].values(),
                key=lambda d: float(d.get("length", 1.0)),
            )

            if "geometry" in best_edge_data and isinstance(best_edge_data["geometry"], LineString):
                coords = list(best_edge_data["geometry"].coords)
                # Check orientation: if first coord is closer to v than u, reverse
                d_first_u = math.hypot(coords[0][0] - self.G.nodes[u]["x"], coords[0][1] - self.G.nodes[u]["y"])
                d_last_u = math.hypot(coords[-1][0] - self.G.nodes[u]["x"], coords[-1][1] - self.G.nodes[u]["y"])
                if d_last_u < d_first_u:
                    coords.reverse()

                # Add intermediate points
                for pt in coords[1:]:
                    prev_x, prev_y = self.points[-1]
                    step_len = math.hypot(pt[0] - prev_x, pt[1] - prev_y)
                    accumulated += step_len
                    self.points.append((float(pt[0]), float(pt[1])))
                    self.cum_dist.append(accumulated)
                    self.segment_target_node.append(v)
            else:
                vx = float(self.G.nodes[v]["x"])
                vy = float(self.G.nodes[v]["y"])
                prev_x, prev_y = self.points[-1]
                step_len = math.hypot(vx - prev_x, vy - prev_y)
                accumulated += step_len
                self.points.append((vx, vy))
                self.cum_dist.append(accumulated)
                self.segment_target_node.append(v)

        self.total_distance_m = accumulated
        self.is_finished = (self.total_distance_m == 0.0)

        # Set initial coordinates at start
        self.x, self.y = self.points[0]
        lon, lat = self.transformer_to_latlon.transform(self.x, self.y)
        self.lat = float(lat)
        self.lon = float(lon)
        self.next_node_ahead = self.path[1] if len(self.path) > 1 else self.path[0]

    def update(self, sim_dt: float) -> None:
        """Advance the walker position by speed * sim_dt.

        Uses bisect on cumulative distances for O(log n) segment lookup.

        Args:
            sim_dt: Simulation delta time in seconds.
        """
        if self.is_finished or len(self.points) < 2:
            return

        self.distance_travelled += self.speed_mps * sim_dt

        # Check destination arrival
        if self.distance_travelled >= self.total_distance_m:
            self.distance_travelled = self.total_distance_m
            self.x, self.y = self.points[-1]
            lon, lat = self.transformer_to_latlon.transform(self.x, self.y)
            self.lat = float(lat)
            self.lon = float(lon)
            self.next_node_ahead = self.path[-1]
            self.is_finished = True
            return

        # Binary search for segment: find index where cum_dist[idx] > distance_travelled
        idx = bisect.bisect_right(self.cum_dist, self.distance_travelled)
        if idx <= 0:
            idx = 1
        elif idx >= len(self.points):
            idx = len(self.points) - 1

        seg_start_dist = self.cum_dist[idx - 1]
        seg_end_dist = self.cum_dist[idx]
        seg_len = max(1e-6, seg_end_dist - seg_start_dist)

        fraction = (self.distance_travelled - seg_start_dist) / seg_len
        p1 = self.points[idx - 1]
        p2 = self.points[idx]

        # Linear interpolation
        self.x = p1[0] + fraction * (p2[0] - p1[0])
        self.y = p1[1] + fraction * (p2[1] - p1[1])

        # Heading angle (0 deg = North, 90 deg = East)
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        self.heading_deg = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0

        # Inverse projection to WGS84
        lon, lat = self.transformer_to_latlon.transform(self.x, self.y)
        self.lat = float(lat)
        self.lon = float(lon)

        # Update node ahead
        seg_idx = idx - 1
        if seg_idx < len(self.segment_target_node):
            self.next_node_ahead = self.segment_target_node[seg_idx]

    def set_new_route(self, new_path: list[int]) -> None:
        """Replace the route from the current position onwards (used during rerouting).

        Args:
            new_path: New sequence of nodes starting from next_node_ahead.
        """
        self.path = list(new_path)
        self._build_polyline()

    def step_manual(self, direction: str) -> Optional[int]:
        """Manually step walker to an adjacent graph intersection in a cardinal direction.

        Args:
            direction: One of ('up', 'down', 'left', 'right').

        Returns:
            Optional[int]: Node ID of destination intersection, or None if no road exits there.
        """
        target_angles = {
            "up": 0.0,       # North
            "right": 90.0,   # East
            "down": 180.0,   # South
            "left": 270.0,   # West
        }
        target = target_angles.get(direction.lower(), 0.0)

        curr = self.current_node
        if curr not in self.G.nodes:
            return None

        # Check all outgoing connected road junctions
        neighbors = list(self.G.successors(curr)) if self.G.is_directed() else list(self.G.neighbors(curr))
        if not neighbors:
            return None

        curr_x = float(self.G.nodes[curr]["x"])
        curr_y = float(self.G.nodes[curr]["y"])

        best_neighbor = None
        min_diff = float("inf")
        best_angle = 0.0

        for nbr in neighbors:
            nx = float(self.G.nodes[nbr]["x"])
            ny = float(self.G.nodes[nbr]["y"])
            dx = nx - curr_x
            dy = ny - curr_y
            bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0

            diff = min(abs(bearing - target), 360.0 - abs(bearing - target))
            if diff < min_diff and diff <= 85.0:  # Within 85 degrees sector
                min_diff = diff
                best_neighbor = nbr
                best_angle = bearing

        if best_neighbor is not None:
            self.current_node = best_neighbor
            self.x = float(self.G.nodes[best_neighbor]["x"])
            self.y = float(self.G.nodes[best_neighbor]["y"])
            lon, lat = self.transformer_to_latlon.transform(self.x, self.y)
            self.lat = float(lat)
            self.lon = float(lon)
            self.heading_deg = best_angle
            self.distance_travelled += math.hypot(self.x - curr_x, self.y - curr_y)
            self.next_node_ahead = best_neighbor
            return best_neighbor

        return None
        self._build_polyline()
        self.distance_travelled = 0.0
