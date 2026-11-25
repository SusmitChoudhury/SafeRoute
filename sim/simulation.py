"""
sim/simulation.py – SafeRoute state machine and simulation engine.

States:
  IDLE        - Awaiting start
  ROUTING     - Calculating optimal path
  MOVING      - Walker advancing along the route
  WARNING_1   - Danger zone detected within 500 m
  REROUTING   - Recalculating route avoiding danger
  WARNING_2   - Displaying reroute notice for 3 s sim time
  ARRIVED     - Destination reached

Rules:
  - Fixed tick loop: simulation logic uses sim_dt only.
  - Drawing never mutates simulation state.
  - Look-ahead index uses binary search with hysteresis.
"""

from enum import Enum, auto
import math
import time
from typing import Optional

import networkx as nx

from config import (
    DEFAULT_START_LATLON,
    DEFAULT_END_LATLON,
    LAMBDA_RISK,
    LOOKAHEAD_M,
    TIME_SCALES,
    WALK_SPEED_MPS,
    BIKE_SPEED_MPS,
)
from core.astar import astar
from core.dijkstra import dijkstra, PathResult
from core.graph_loader import load_graph, snap_to_node
from core.lookahead import (
    EntryIndex,
    build_entry_index,
    query_ahead,
    route_polyline,
)
from core.risk_model import Incident, compute_edge_risk, make_weight_fn
from core.router import compare_modes, compute_route, compute_route_alternatives, reroute
from core.travel_model import (
    MODE_SPEED_MPS,
    add_travel_times,
    calculate_route_stats,
)
from sim.incidents import IncidentStore
from sim.logger import SimLogger
from sim.walker import Walker
from ui.audio import AudioManager


class SimState(Enum):
    IDLE = auto()
    ROUTING = auto()
    MOVING = auto()
    WARNING_1 = auto()
    REROUTING = auto()
    WARNING_2 = auto()
    ARRIVED = auto()


class Simulation:
    """Core simulation engine driving the detect-and-reroute state machine."""

    def __init__(
        self,
        mode: str = "walk",
        speed_scale: int = 10,
        logger: Optional[SimLogger] = None,
        db_store: Optional[IncidentStore] = None,
    ):
        self.mode = mode.lower()
        self.time_scale = speed_scale
        self.logger = logger if logger else SimLogger()
        self.incident_store = db_store if db_store else IncidentStore()
        self.audio = AudioManager()

        self.state = SimState.IDLE
        self.is_paused = False
        self.sim_time = 0.0

        # Feature flags
        self.explain_mode = False
        self.show_heatmap = False
        self.manual_mode = False

        # Endpoints
        self.start_latlon = DEFAULT_START_LATLON
        self.end_latlon = DEFAULT_END_LATLON
        self.start_node: Optional[int] = None
        self.end_node: Optional[int] = None

        # Active graph
        self.G: nx.MultiDiGraph = load_graph(self.mode)
        add_travel_times(self.G, self.mode)

        # Active route and history
        self.current_route: list[int] = []
        self.previous_route: list[int] = []
        self.route_result: Optional[PathResult] = None
        self.route_stats: dict[str, float] = {}
        self.route_risks: dict = {}

        # Look-ahead detection
        self.polyline_pts = None
        self.polyline_cum = None
        self.lookahead_index = EntryIndex([], [])
        self.triggered_incidents: set[int] = set()

        # Multi-modal travel times
        self.all_mode_etas: dict[str, dict[str, float]] = {}

        # Walker
        self.walker: Optional[Walker] = None

        # Warning banner states
        self.warning_timer = 0.0
        self.warning_1_banner = ""
        self.warning_2_banner = ""

        # Performance summary metrics
        self.reroute_count = 0
        self.incidents_avoided = 0
        self.warnings_count = 0

        # Detection mode: "instant" (default) or "lookahead" (500m)
        self.detection_mode = "instant"
        self.pipeline_step = 0
        self.pipeline_timer = 0.0
        self.route_alternatives: dict[str, dict] = {}
        self.active_route_name = "balanced"
        self.run_number = 1

        self.logger.log("INFO", "system", f"--- run {self.run_number} started ---", self.sim_time)
        self.logger.log("INFO", "startup", f"SafeRoute simulator v1.0, mode={self.mode}, seed=42", self.sim_time)
        self.logger.log("WARN", "data", "incident data is SIMULATED (seed=42)", self.sim_time)

        self._snap_endpoints()
        self._check_endpoint_hazard("start", *self.start_latlon)
        self._check_endpoint_hazard("end", *self.end_latlon)
        self._calculate_initial_route()

    def _snap_endpoints(self) -> None:
        """Snap start and end points to nearest graph nodes."""
        self.start_node, s_dist = snap_to_node(self.G, *self.start_latlon)
        self.end_node, e_dist = snap_to_node(self.G, *self.end_latlon)
        self.logger.log(
            "INFO",
            "snap",
            f"start -> node {self.start_node} ({s_dist:.1f} m), end -> node {self.end_node} ({e_dist:.1f} m)",
            self.sim_time,
        )

    def _check_endpoint_hazard(self, which: str, lat: float, lon: float) -> None:
        """Check and log a prominent WARN if start or end pin is placed inside an active hazard circle."""
        label = "GOAL" if which.lower() in ("end", "goal") else "START"
        active = self.incident_store.get_active_incidents()
        for inc in active:
            d_lat = (lat - inc.lat) * 111320.0
            d_lon = (lon - inc.lon) * 111320.0 * math.cos(math.radians(lat))
            d_m = math.hypot(d_lat, d_lon)
            if d_m <= inc.radius_m:
                self.logger.log(
                    "WARN",
                    "endpoint",
                    f"{label} marker placed inside danger zone #{inc.id} ({inc.type}, radius {inc.radius_m:.0f} m)",
                    self.sim_time,
                )

    def _rebuild_lookahead_index(self) -> None:
        """Recompute route polyline and rebuild the sorted look-ahead index."""
        if not self.current_route:
            return

        self.polyline_pts, self.polyline_cum = route_polyline(self.G, self.current_route)
        active_incidents = self.incident_store.get_active_incidents()
        self.lookahead_index = build_entry_index(self.polyline_pts, self.polyline_cum, active_incidents)

    def _calculate_initial_route(self) -> None:
        """Compute the initial optimal path using A* and record Dijkstra comparison."""
        if not self.start_node or not self.end_node:
            return

        active_incidents = self.incident_store.get_active_incidents()
        self.route_risks = compute_edge_risk(self.G, active_incidents, self.mode)
        weight_fn = make_weight_fn(self.G, self.route_risks, self.mode, active_incidents)

        # 1. Dijkstra run (for diagnostic comparison and explain mode)
        d_res = dijkstra(self.G, self.start_node, self.end_node, weight_fn=weight_fn, explain=self.explain_mode)
        self.logger.log(
            "CALC",
            "dijkstra",
            f"explored {d_res.explored} nodes, {d_res.relaxations} relaxations, {d_res.elapsed_ms:.1f} ms, cost {d_res.cost:.1f} s",
            self.sim_time,
        )

        # 2. A* run (used for the simulation route)
        v_max = 50.0 / 3.6 if self.mode in ("car", "drive") else MODE_SPEED_MPS.get(self.mode, 1.39)
        a_res = astar(self.G, self.start_node, self.end_node, weight_fn=weight_fn, v_max=v_max, explain=self.explain_mode)
        self.logger.log(
            "CALC",
            "astar",
            f"explored {a_res.explored} nodes, {a_res.relaxations} relaxations, {a_res.elapsed_ms:.1f} ms, cost {a_res.cost:.1f} s",
            self.sim_time,
        )

        if math.isinf(a_res.cost) or not a_res.path:
            self.logger.log("WARN", "router", "no path in blocked graph - using penalty fallback", self.sim_time)
            weight_fn_fb = make_weight_fn(self.G, self.route_risks, self.mode, active_incidents, fallback=True)
            a_res = astar(self.G, self.start_node, self.end_node, weight_fn=weight_fn_fb, v_max=v_max)

        self.current_route = list(a_res.path)
        self.route_result = a_res
        self.route_stats = calculate_route_stats(self.G, self.current_route, self.mode)

        speed_mps = MODE_SPEED_MPS.get(self.mode, WALK_SPEED_MPS)
        self.walker = Walker(self.G, self.current_route, speed_mps=speed_mps)

        self._rebuild_lookahead_index()
        self.triggered_incidents.clear()

        # Compute initial route risk sum
        total_risk = sum(
            self.route_risks.get((self.current_route[i], self.current_route[i+1], 0), 0.0)
            for i in range(len(self.current_route) - 1)
        )

        self.logger.log(
            "ROUTE",
            "router",
            f"route 1 chosen: {self.route_stats['length_m']:.0f} m, {len(self.current_route)} nodes, risk {total_risk:.2f}",
            self.sim_time,
        )
        self._check_route_campus_footpaths(self.current_route)

        # Compute candidate alternative routes (Fastest, Balanced, Safest)
        self.route_alternatives = compute_route_alternatives(
            self.G, self.start_node, self.end_node, active_incidents, self.mode, risks=self.route_risks
        )
        for alt in self.route_alternatives.values():
            alt["full_path"] = list(alt["path"])
        self.active_route_name = "balanced"

        self._compute_all_mode_etas()

    def _check_route_campus_footpaths(self, route: list[int]) -> None:
        """Check if route traverses campus footpaths/service tracks not always visible on standard street tiles."""
        if not route or not self.G:
            return
        has_footway = False
        for i in range(len(route) - 1):
            u, v = route[i], route[i + 1]
            if self.G.has_edge(u, v):
                best = min(self.G[u][v].values(), key=lambda d: float(d.get("length", 1.0)))
                hw = best.get("highway")
                if isinstance(hw, list):
                    if any(h in ("footway", "path", "pedestrian", "track") for h in hw):
                        has_footway = True
                        break
                elif hw in ("footway", "path", "pedestrian", "track"):
                    has_footway = True
                    break
        if has_footway:
            self.logger.log(
                "WARN",
                "route",
                "route follows campus footpaths (may not be visible on standard street tiles)",
                self.sim_time,
            )

    def _compute_all_mode_etas(self) -> None:
        """Calculate and log route travel times across all three modes (walk, bike, car)."""
        active_incidents = self.incident_store.get_active_incidents()
        self.all_mode_etas = compare_modes(self.start_latlon, self.end_latlon, active_incidents)

        mode_summaries = []
        for m in ["walk", "bike", "car"]:
            stats = self.all_mode_etas.get(m, {})
            l_m = stats.get("length_m", 0.0)
            e_min = stats.get("eta_minutes", 0.0)
            mode_summaries.append(f"{m} {l_m:.0f} m {e_min:.1f} min")

        if mode_summaries:
            self.logger.log("CALC", "modes", " | ".join(mode_summaries), self.sim_time)

    def set_detection_mode(self, mode: str) -> None:
        """Switch detection mode between 'instant' and 'lookahead' (500m)."""
        m = mode.lower()
        if m in ("instant", "lookahead"):
            self.detection_mode = m
            self.logger.log("INFO", "config", f"detection mode set to {m.upper()}", self.sim_time)

    def trigger_warning_1_and_reroute(self, inc_id: int, s_enter: float, gap_m: float) -> None:
        """Execute the 6-step numbered rerouting pipeline in real-time (<100 ms)."""
        t0 = time.perf_counter()
        active_incidents = self.incident_store.get_active_incidents()
        inc = next((i for i in active_incidents if i.id == inc_id), None)
        inc_type = inc.type if inc else "incident"
        inc_lat = inc.lat if inc else 0.0
        inc_lon = inc.lon if inc else 0.0
        inc_rad = inc.radius_m if inc else 100.0

        self.warnings_count += 1
        self.state = SimState.WARNING_1
        self.audio.play_warning_1()
        self.pipeline_step = 1

        # Header & STEP 1/6: Detect
        self.logger.log("ALERT", "incident", f"#{inc_id} {inc_type} dropped at ({inc_lat:.4f}, {inc_lon:.4f}), radius {inc_rad:.0f} m", self.sim_time)
        self.logger.log("STEP 1/6", "detect", f"zone intersects the remaining route {gap_m:.0f} m ahead", self.sim_time)

        # STEP 2/6: Recompute edge weights
        self.pipeline_step = 2
        self.route_risks = compute_edge_risk(self.G, active_incidents, self.mode)
        affected_edges = [(u, v, k, r) for (u, v, k), r in self.route_risks.items() if r > 0.0]
        n_aff = len(affected_edges)
        if affected_edges:
            worst_edge = max(affected_edges, key=lambda item: item[3])
            u_w, v_w, k_w, r_w = worst_edge
            t_w = float(self.G[u_w][v_w][k_w].get("travel_time", self.G[u_w][v_w][k_w].get("base_time", 1.0)))
            w_w = t_w * (1.0 + 2.0 * r_w)
            self.logger.log("STEP 2/6", "weights", f"{n_aff} edges affected; worst: t = {t_w:.1f} s, r = {r_w:.2f}, w = {t_w:.1f}*(1+2.0*{r_w:.2f}) = {w_w:.1f} s", self.sim_time)
        else:
            self.logger.log("STEP 2/6", "weights", "0 edges directly affected", self.sim_time)

        # STEP 3/6: Search (Dijkstra)
        self.pipeline_step = 3
        origin_node = self.walker.next_node_ahead if (self.walker and self.walker.next_node_ahead) else self.start_node
        try:
            curr_idx = self.current_route.index(origin_node)
            prefix = self.current_route[:curr_idx]
        except ValueError:
            prefix = []

        weight_fn = make_weight_fn(self.G, self.route_risks, self.mode, active_incidents, lam=2.0)
        d_res = dijkstra(self.G, origin_node, self.end_node, weight_fn=weight_fn)
        self.logger.log("STEP 3/6", "search", f"Dijkstra node {origin_node} -> {self.end_node}: explored {d_res.explored} nodes, {d_res.relaxations} relaxations, {d_res.elapsed_ms:.1f} ms", self.sim_time)

        # STEP 4/6: Options (Fastest, Balanced, Safest)
        self.pipeline_step = 4
        alts = compute_route_alternatives(
            self.G, origin_node, self.end_node, active_incidents, self.mode, risks=self.route_risks
        )
        for alt in alts.values():
            alt["full_path"] = prefix + list(alt["path"])
        self.route_alternatives = alts
        self.active_route_name = "balanced"

        f_info = alts.get("fastest", {})
        b_info = alts.get("balanced", {})
        s_info = alts.get("safest", {})
        self.logger.log(
            "STEP 4/6",
            "options",
            f"Fastest {f_info.get('length_m', 0):.0f} m {f_info.get('eta_minutes', 0):.1f} min | "
            f"Balanced {b_info.get('length_m', 0):.0f} m {b_info.get('eta_minutes', 0):.1f} min | "
            f"Safest {s_info.get('length_m', 0):.0f} m {s_info.get('eta_minutes', 0):.1f} min",
            self.sim_time,
        )

        # STEP 5/6: Compare old and new
        self.pipeline_step = 5
        chosen_path = b_info.get("path", d_res.path)
        new_full_route = prefix + list(chosen_path)
        new_stats = calculate_route_stats(self.G, new_full_route, self.mode)
        old_stats = self.route_stats
        extra_dist = max(0.0, new_stats["length_m"] - old_stats.get("length_m", new_stats["length_m"]))
        extra_min = max(0.0, new_stats["eta_minutes"] - old_stats.get("eta_minutes", new_stats["eta_minutes"]))

        old_r = sum(self.route_risks.get((self.current_route[i], self.current_route[i+1], 0), 0.0) for i in range(len(self.current_route)-1))
        new_r = sum(self.route_risks.get((new_full_route[i], new_full_route[i+1], 0), 0.0) for i in range(len(new_full_route)-1))
        self.logger.log("STEP 5/6", "compare", f"old -> new: +{extra_dist:.0f} m, +{extra_min:.1f} min, risk {old_r:.2f} -> {new_r:.2f}", self.sim_time)

        # STEP 6/6: Switch
        self.pipeline_step = 6
        self.previous_route = list(self.current_route)
        self.current_route = new_full_route
        self.route_result = d_res
        self.route_stats = new_stats
        self.reroute_count += 1
        self.incidents_avoided += 1
        self.walker.set_new_route(self.current_route)
        self._rebuild_lookahead_index()
        self.triggered_incidents.add(inc_id)
        self._check_route_campus_footpaths(self.current_route)
        self.logger.log("STEP 6/6", "switch", f"walker continues on Balanced from node {origin_node}", self.sim_time)

        # DONE: Reroute completed & shortcut check
        total_ms = (time.perf_counter() - t0) * 1000
        f_min = f_info.get("eta_minutes", 0.0)
        b_min = b_info.get("eta_minutes", 0.0)
        f_risk = f_info.get("risk", 0.0)
        old_min = old_stats.get("eta_minutes", b_min)

        if b_min < old_min - 0.05:
            saved_min = old_min - b_min
            shortcut_msg = f"SHORTCUT found: -{saved_min:.1f} min via alternative road"
        elif f_min < b_min - 0.05:
            diff_min = b_min - f_min
            shortcut_msg = f"No shorter alternative exists, or shortest road ({f_min:.1f} min) has higher risk {f_risk:.2f} (+{diff_min:.1f} min)"
        else:
            shortcut_msg = f"No shorter alternative exists than {b_min:.1f} min"

        self.logger.log("DONE", "reroute", f"completed in {total_ms:.1f} ms; SHORTCUT: {shortcut_msg}", self.sim_time)

        # Transition to WARNING_2 state (banner shown for 3 s sim time)
        self.state = SimState.WARNING_2
        self.audio.play_warning_2()
        self.warning_timer = 3.0
        self.pipeline_timer = 3.0
        self.warning_2_banner = f"WARNING 2: Rerouted! Avoids {inc_type} #{inc_id} (+{extra_dist:.0f} m, +{extra_min:.1f} min)"

    def drop_incident(self, lat: float, lon: float, inc_type: str = "accident") -> int:
        """Drop a new danger zone incident and recheck route look-ahead immediately.

        Args:
            lat: Latitude.
            lon: Longitude.
            inc_type: Danger type.

        Returns:
            int: Inserted incident ID.
        """
        inc_id = self.incident_store.add_incident(inc_type, lat, lon, source="live")
        self._rebuild_lookahead_index()

        horizon = float("inf") if self.detection_mode == "instant" else LOOKAHEAD_M
        if self.state in (SimState.MOVING, SimState.WARNING_2) and self.walker:
            s_now = self.walker.distance_travelled
            hits = query_ahead(self.lookahead_index, s_now, horizon)
            if inc_id in hits and inc_id not in self.triggered_incidents:
                self.triggered_incidents.add(inc_id)
                idx = self.lookahead_index.entry_ids.index(inc_id)
                s_enter = self.lookahead_index.entry_keys[idx]
                gap = s_enter - s_now
                self.trigger_warning_1_and_reroute(inc_id, s_enter, gap)
        elif self.state == SimState.IDLE:
            hits = query_ahead(self.lookahead_index, 0.0, float("inf"))
            if inc_id in hits:
                self._calculate_initial_route()
        else:
            self.logger.log("ALERT", "incident", f"#{inc_id} {inc_type} dropped at ({lat:.4f}, {lon:.4f})", self.sim_time)

        return inc_id

    def move_incident(self, inc_id: int, lat: float, lon: float) -> bool:
        """Update the position of an existing incident (supports drag-and-drop) and recheck look-ahead."""
        success = self.incident_store.move_incident(inc_id, lat, lon)
        if not success:
            return False

        self.triggered_incidents.discard(inc_id)
        self._rebuild_lookahead_index()
        active_now = self.incident_store.get_active_incidents()
        self.route_risks = compute_edge_risk(self.G, active_now, self.mode)

        horizon = float("inf") if self.detection_mode == "instant" else LOOKAHEAD_M
        if self.state in (SimState.MOVING, SimState.WARNING_2) and self.walker:
            s_now = self.walker.distance_travelled
            hits = query_ahead(self.lookahead_index, s_now, horizon)
            if inc_id in hits:
                self.triggered_incidents.add(inc_id)
                idx = self.lookahead_index.entry_ids.index(inc_id)
                s_enter = self.lookahead_index.entry_keys[idx]
                gap = s_enter - s_now
                self.trigger_warning_1_and_reroute(inc_id, s_enter, gap)
        elif self.state == SimState.IDLE:
            hits = query_ahead(self.lookahead_index, 0.0, float("inf"))
            if inc_id in hits:
                self._calculate_initial_route()
        else:
            self.logger.log("INFO", "incident", f"#{inc_id} repositioned to ({lat:.4f}, {lon:.4f})", self.sim_time)

        return True

    def remove_incident_near(self, lat: float, lon: float, max_dist_m: float = 120.0) -> Optional[int]:
        """Remove the closest active incident near the specified (lat, lon) coordinates.

        Args:
            lat: Click latitude.
            lon: Click longitude.
            max_dist_m: Max radius in metres to consider a click as hitting an incident.

        Returns:
            Optional[int]: Removed incident ID, or None if no incident was within range.
        """
        active_incidents = self.incident_store.get_active_incidents()
        if not active_incidents:
            return None

        # Convert click point to UTM using graph loader CRS
        utm_x, utm_y = self.incident_store.transformer.transform(lon, lat)

        closest_inc = None
        min_dist = float("inf")
        for inc in active_incidents:
            dist = math.hypot(inc.utm_x - utm_x, inc.utm_y - utm_y)
            if dist < min_dist:
                min_dist = dist
                closest_inc = inc

        if closest_inc and min_dist <= max_dist_m:
            inc_id = closest_inc.id
            self.incident_store.remove_incident(inc_id)
            self.triggered_incidents.discard(inc_id)
            self.logger.log("INFO", "incident", f"#{inc_id} {closest_inc.type} removed", self.sim_time)

            # Re-evaluate route and lookahead index
            self._rebuild_lookahead_index()
            # If idle or moving, re-compute route risks
            active_now = self.incident_store.get_active_incidents()
            self.route_risks = compute_edge_risk(self.G, active_now, self.mode)
            return inc_id
        return None

    def set_endpoint(self, which: str, lat: float, lon: float) -> tuple[Optional[int], float]:
        """Update start or end endpoint and recalculate route.

        Args:
            which: 'start' or 'end'.
            lat: New latitude.
            lon: New longitude.

        Returns:
            tuple[Optional[int], float]: (snapped_node_id, snap_distance_m)
        """
        if which == "start":
            self.start_latlon = (lat, lon)
            self.start_node, dist = snap_to_node(self.G, lat, lon)
            self._check_endpoint_hazard("start", lat, lon)
            self.logger.log("INFO", "snap", f"start relocated to ({lat:.4f}, {lon:.4f}) -> node {self.start_node} ({dist:.1f} m)", self.sim_time)
            if self.state == SimState.IDLE or not self.walker:
                self._calculate_initial_route()
            return self.start_node, dist

        elif which == "end":
            self.end_latlon = (lat, lon)
            self.end_node, dist = snap_to_node(self.G, lat, lon)
            self._check_endpoint_hazard("end", lat, lon)
            self.logger.log("INFO", "snap", f"goal relocated to ({lat:.4f}, {lon:.4f}) -> node {self.end_node} ({dist:.1f} m)", self.sim_time)

            if self.state == SimState.IDLE or not self.walker:
                self._calculate_initial_route()
            elif self.state in (SimState.MOVING, SimState.WARNING_2):
                active_incidents = self.incident_store.get_active_incidents()
                origin_node = self.walker.next_node_ahead if (self.walker and self.walker.next_node_ahead) else self.start_node
                new_res, comp = reroute(self.G, origin_node, self.end_node, active_incidents, self.mode, self.route_result)
                try:
                    curr_idx = self.current_route.index(origin_node)
                    prefix = self.current_route[:curr_idx]
                except ValueError:
                    prefix = []
                self.previous_route = list(self.current_route)
                self.current_route = prefix + list(new_res.path)
                self.route_result = new_res
                self.route_stats = calculate_route_stats(self.G, self.current_route, self.mode)
                self.walker.set_new_route(self.current_route)
                self._rebuild_lookahead_index()
                self._check_route_campus_footpaths(self.current_route)
            return self.end_node, dist

        return None, 0.0

    def select_route(self, choice: str) -> bool:
        """Switch walker to follow one of the computed alternative routes ('fastest', 'balanced', 'safest')."""
        key = choice.lower()
        if key not in self.route_alternatives:
            return False
        alt = self.route_alternatives[key]
        path_to_follow = alt.get("full_path", alt.get("path", []))
        if not path_to_follow:
            return False

        self.active_route_name = key
        self.previous_route = list(self.current_route)
        self.current_route = list(path_to_follow)
        self.route_stats = calculate_route_stats(self.G, self.current_route, self.mode)

        if self.walker:
            if self.state == SimState.IDLE:
                speed_mps = MODE_SPEED_MPS.get(self.mode, WALK_SPEED_MPS)
                self.walker = Walker(self.G, self.current_route, speed_mps=speed_mps)
            else:
                self.walker.set_new_route(self.current_route)

        self._rebuild_lookahead_index()
        self.logger.log(
            "ROUTE",
            "router",
            f"switched to {alt['name']} route: {alt['length_m']:.0f} m, {alt['eta_minutes']:.1f} min, risk {alt['risk']:.2f}",
            self.sim_time,
        )
        return True

    def cycle_route(self) -> str:
        """Cycle through available route alternatives (Fastest -> Balanced -> Safest)."""
        keys = ["fastest", "balanced", "safest"]
        if self.active_route_name in keys:
            idx = (keys.index(self.active_route_name) + 1) % len(keys)
        else:
            idx = 0
        next_choice = keys[idx]
        self.select_route(next_choice)
        return next_choice

    def set_mode(self, new_mode: str) -> None:
        """Switch simulation travel mode (walk, bike, car) and recompute route."""
        m = new_mode.lower()
        if m not in ("walk", "bike", "car", "drive"):
            return
        if m == "drive":
            m = "car"

        if m == self.mode:
            return

        self.mode = m
        self.G = load_graph(self.mode)
        add_travel_times(self.G, self.mode)
        self._snap_endpoints()
        self._calculate_initial_route()
        self.logger.log("INFO", "mode", f"switched travel mode to {self.mode.upper()}", self.sim_time)

    def set_time_scale(self, scale: int) -> None:
        """Set simulation time acceleration factor."""
        self.time_scale = max(1, scale)
        self.logger.log("INFO", "speed", f"simulation speed scale set to x{self.time_scale}", self.sim_time)

    def cycle_speed(self, forward: bool = True) -> None:
        """Cycle speed scale through standard tiers: 1x -> 10x -> 50x."""
        tiers = [1, 10, 50]
        try:
            curr_idx = tiers.index(self.time_scale)
        except ValueError:
            curr_idx = 1
        new_idx = (curr_idx + 1) % len(tiers) if forward else (curr_idx - 1) % len(tiers)
        self.set_time_scale(tiers[new_idx])

    def toggle_explain(self) -> None:
        """Toggle verbose Dijkstra explain mode logging."""
        self.explain_mode = not self.explain_mode
        state_str = "ENABLED" if self.explain_mode else "DISABLED"
        self.logger.log("INFO", "explain", f"explain mode {state_str}", self.sim_time)
        if self.explain_mode and self.start_node and self.end_node:
            active_incidents = self.incident_store.get_active_incidents()
            weight_fn = make_weight_fn(self.G, self.route_risks, self.mode, active_incidents)
            d_res = dijkstra(self.G, self.start_node, self.end_node, weight_fn=weight_fn, explain=True)
            for trace_line in d_res.trace[:8]:
                self.logger.log("CALC", "explain", trace_line, self.sim_time)

    def toggle_heatmap(self) -> None:
        """Toggle road network risk heat-map overlay."""
        self.show_heatmap = not self.show_heatmap
        state_str = "ENABLED" if self.show_heatmap else "DISABLED"
        self.logger.log("INFO", "heatmap", f"risk heat-map {state_str}", self.sim_time)
        if self.show_heatmap:
            active_incidents = self.incident_store.get_active_incidents()
            self.route_risks = compute_edge_risk(self.G, active_incidents, self.mode)

    def start_or_pause(self) -> None:
        """Toggle between moving and paused state."""
        if self.state == SimState.IDLE:
            self.state = SimState.MOVING
            self.logger.log("INFO", "sim", "simulation started", self.sim_time)
        elif self.state in (SimState.MOVING, SimState.WARNING_2):
            self.is_paused = not self.is_paused
            status_str = "paused" if self.is_paused else "resumed"
            self.logger.log("INFO", "sim", f"simulation {status_str}", self.sim_time)

    def reset(self) -> None:
        """Reset the simulation back to initial state."""
        self.incident_store.clear_live_incidents()
        self.state = SimState.IDLE
        self.is_paused = False
        self.sim_time = 0.0
        self.warning_timer = 0.0
        self.reroute_count = 0
        self.incidents_avoided = 0
        self.warnings_count = 0
        self.previous_route = []
        self.triggered_incidents.clear()
        self.run_number += 1
        self.logger.log("INFO", "system", f"--- run {self.run_number} started ---", self.sim_time)
        self.logger.log("INFO", "sim", "simulation reset", self.sim_time)
        self._calculate_initial_route()

    def update(self, real_dt: float) -> None:
        """Advance the simulation tick loop.

        Args:
            real_dt: Wall-clock frame delta time in seconds.
        """
        if self.is_paused or self.state in (SimState.IDLE, SimState.ARRIVED):
            return

        sim_dt = real_dt * self.time_scale
        self.sim_time += sim_dt

        # Handle Warning 2 banner countdown (displays for 3 s sim time)
        if self.state == SimState.WARNING_2:
            self.warning_timer -= sim_dt
            if self.warning_timer <= 0:
                self.state = SimState.MOVING

        if self.pipeline_timer > 0.0:
            self.pipeline_timer -= sim_dt
            if self.pipeline_timer <= 0.0:
                self.pipeline_step = 0

        # Advance walker
        if self.walker and not self.walker.is_finished:
            self.walker.update(sim_dt)

            # Check arrival
            if self.walker.is_finished:
                self.state = SimState.ARRIVED
                total_min = self.sim_time / 60.0
                self.logger.log("INFO", "walker", f"destination reached in {total_min:.1f} min (sim time)", self.sim_time)
                self.logger.log(
                    "INFO",
                    "summary",
                    f"distance {self.walker.total_distance_m:.0f} m, reroutes {self.reroute_count}, incidents avoided {self.incidents_avoided}, warnings {self.warnings_count}",
                    self.sim_time,
                )
                return

            # Look-ahead query when MOVING
            if self.state == SimState.MOVING:
                s_now = self.walker.distance_travelled
                horizon = float("inf") if self.detection_mode == "instant" else LOOKAHEAD_M
                hits = query_ahead(self.lookahead_index, s_now, horizon)
                for inc_id in hits:
                    if inc_id not in self.triggered_incidents:
                        self.triggered_incidents.add(inc_id)
                        idx = self.lookahead_index.entry_ids.index(inc_id)
                        s_enter = self.lookahead_index.entry_keys[idx]
                        gap = s_enter - s_now
                        self.trigger_warning_1_and_reroute(inc_id, s_enter, gap)
                        break
