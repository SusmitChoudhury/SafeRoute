"""
tools/web_server.py – World-Class Localhost Simulator (CSM216 Project).

Features:
  - Official OpenStreetMap & Esri Satellite retina vector tiles (100% free, NO API KEY)
  - Pure Python standard library backend (http.server) – NO external web frameworks
  - Real-time bidirectional JSON API powering Dijkstra, A*, Look-ahead, and Risk models
  - Live interactive DRAG-AND-DROP hazards: drag accidents/hazards directly onto the road
    during simulation, triggering real-time look-ahead detection and dynamic A* rerouting
  - Floating Glassmorphism HUD, high-visibility 15px bold monospace algorithm log console
  - Instant interactive control buttons with Web Audio acoustic feedback and tactile active states
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Local writable matplotlib cache
os.environ["MPLCONFIGDIR"] = str(PROJECT_ROOT / ".cache" / "matplotlib")
os.environ["SDL_VIDEODRIVER"] = "dummy"

from config import (
    DEFAULT_START_LATLON,
    DEFAULT_END_LATLON,
    INCIDENT_TYPES,
)
from core.lookahead import route_to_latlon_polyline
from core.risk_model import compute_edge_risk
from sim.logger import SimLogger
from sim.scripted_demo import setup_scripted_demo
from sim.simulation import SimState, Simulation
import pyproj
from shapely.geometry import LineString


class SimulationHost:
    """Manages the background simulation state and provides thread-safe JSON state snapshots."""

    def __init__(self, mode: str = "walk", speed: int = 10):
        self.logger = SimLogger()
        self.sim = Simulation(mode=mode, speed_scale=speed, logger=self.logger)
        self.active_inc_type = "accident"
        self.lock = threading.Lock()
        self.running = True
        self._cached_graph_edges = None
        self._transformer = pyproj.Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)

    def get_graph_edges(self) -> list[list[list[float]]]:
        """Return cached lat/lon polylines for all edges in the graph."""
        with self.lock:
            if self._cached_graph_edges is not None:
                return self._cached_graph_edges

            G = self.sim.G
            all_edges = []
            for u, v, k, d in G.edges(keys=True, data=True):
                if "geometry" in d and isinstance(d["geometry"], LineString):
                    coords = list(d["geometry"].coords)
                    xs = [c[0] for c in coords]
                    ys = [c[1] for c in coords]
                    lons, lats = self._transformer.transform(xs, ys)
                    all_edges.append([[float(la), float(lo)] for la, lo in zip(lats, lons)])
                else:
                    lat_u = float(G.nodes[u].get("lat", G.nodes[u]["y"]))
                    lon_u = float(G.nodes[u].get("lon", G.nodes[u]["x"]))
                    lat_v = float(G.nodes[v].get("lat", G.nodes[v]["y"]))
                    lon_v = float(G.nodes[v].get("lon", G.nodes[v]["x"]))
                    all_edges.append([[lat_u, lon_u], [lat_v, lon_v]])
            self._cached_graph_edges = all_edges
            return all_edges

    def loop(self) -> None:
        """Background 20 FPS simulation advancement loop."""
        last_t = time.perf_counter()
        while self.running:
            now_t = time.perf_counter()
            dt = min(0.1, now_t - last_t)
            last_t = now_t

            with self.lock:
                self.sim.update(dt)

            time.sleep(0.04)

    def get_state(self) -> dict:
        """Extract a complete JSON-serializable snapshot of the simulation."""
        with self.lock:
            sim = self.sim

            # Route coordinates: full road geometry polyline (including curves) matching walker path
            current_route_coords = []
            if sim.current_route and sim.G:
                current_route_coords = route_to_latlon_polyline(sim.G, sim.current_route)

            previous_route_coords = []
            if sim.previous_route and sim.G:
                previous_route_coords = route_to_latlon_polyline(sim.G, sim.previous_route)

            # Incidents
            active_incidents = sim.incident_store.get_active_incidents()
            incidents_data = [
                {
                    "id": inc.id,
                    "type": inc.type,
                    "lat": inc.lat,
                    "lon": inc.lon,
                    "radius_m": inc.radius_m,
                    "severity": inc.severity,
                    "blocking": bool(inc.blocking),
                    "source": inc.source,
                }
                for inc in active_incidents
            ]

            # Walker
            walker_data = None
            if sim.walker:
                walker_data = {
                    "lat": sim.walker.lat,
                    "lon": sim.walker.lon,
                    "heading": sim.walker.heading_deg,
                    "distance_m": sim.walker.distance_travelled,
                    "total_m": sim.walker.total_distance_m,
                    "speed_mps": sim.walker.speed_mps,
                    "is_finished": sim.walker.is_finished,
                }

            # Candidate Route Alternatives (P3: Fastest, Balanced, Safest)
            alternatives_data = {}
            if sim.route_alternatives and sim.G:
                for k, alt in sim.route_alternatives.items():
                    p = alt.get("full_path", alt.get("path", []))
                    poly = route_to_latlon_polyline(sim.G, p) if (p and sim.G) else []
                    alternatives_data[k] = {
                        "id": k,
                        "name": alt.get("name", k.capitalize()),
                        "lambda": alt.get("lambda", 0.0),
                        "length_m": round(alt.get("length_m", 0.0), 1),
                        "eta_minutes": round(alt.get("eta_minutes", 0.0), 1),
                        "risk": round(alt.get("risk", 0.0), 2),
                        "cost_s": round(alt.get("cost_s", 0.0), 1),
                        "polyline": poly,
                        "is_active": (k == sim.active_route_name),
                        "is_duplicate": alt.get("is_duplicate", False),
                        "duplicate_of": alt.get("duplicate_of"),
                    }

            # Recent logs (last 55 lines)
            raw_lines = sim.logger.lines()
            log_entries = [
                {"level": lvl, "text": txt}
                for lvl, txt in raw_lines[-55:]
            ]

            return {
                "state": sim.state.name,
                "is_paused": sim.is_paused,
                "mode": sim.mode,
                "speed_scale": sim.time_scale,
                "sim_time": round(sim.sim_time, 1),
                "detection_mode": sim.detection_mode,
                "pipeline_step": sim.pipeline_step,
                "explain_mode": sim.explain_mode,
                "show_heatmap": sim.show_heatmap,
                "active_inc_type": self.active_inc_type,
                "start_latlon": list(sim.start_latlon),
                "end_latlon": list(sim.end_latlon),
                "route_stats": sim.route_stats,
                "route_alternatives": alternatives_data,
                "active_route_name": sim.active_route_name,
                "all_mode_etas": sim.all_mode_etas,
                "reroute_count": sim.reroute_count,
                "incidents_avoided": sim.incidents_avoided,
                "warnings_count": sim.warnings_count,
                "warning_1_banner": sim.warning_1_banner if sim.state == SimState.WARNING_1 else "",
                "warning_2_banner": sim.warning_2_banner if (sim.state == SimState.WARNING_2 or sim.warning_timer > 0) else "",
                "current_route": current_route_coords,
                "previous_route": previous_route_coords,
                "incidents": incidents_data,
                "walker": walker_data,
                "logs": log_entries,
            }


_host: SimulationHost = None


class SafeRouteWebHandler(BaseHTTPRequestHandler):
    """HTTP Request handler serving HTML5/JS app and REST endpoints."""

    def log_message(self, format, *args):
        # Suppress spammy HTTP access logs
        pass

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(self._get_html().encode("utf-8"))

        elif path == "/api/state":
            state = _host.get_state()
            payload = json.dumps(state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(payload)

        elif path == "/api/graph_edges":
            edges = _host.get_graph_edges()
            payload = json.dumps(edges).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(payload)

        elif path.startswith("/static/"):
            rel_path = path[len("/static/"):].lstrip("/")
            local_file = (PROJECT_ROOT / "static" / rel_path).resolve()
            static_dir = (PROJECT_ROOT / "static").resolve()
            try:
                local_file.relative_to(static_dir)
            except ValueError:
                self.send_response(403)
                self.end_headers()
                return

            if local_file.is_file():
                self.send_response(200)
                if rel_path.endswith(".js"):
                    self.send_header("Content-Type", "application/javascript; charset=utf-8")
                elif rel_path.endswith(".css"):
                    self.send_header("Content-Type", "text/css; charset=utf-8")
                elif rel_path.endswith(".png"):
                    self.send_header("Content-Type", "image/png")
                elif rel_path.endswith(".jpg") or rel_path.endswith(".jpeg"):
                    self.send_header("Content-Type", "image/jpeg")
                elif rel_path.endswith(".svg"):
                    self.send_header("Content-Type", "image/svg+xml")
                else:
                    self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                with open(local_file, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if path == "/api/action":
            action = data.get("action", "")
            val = data.get("val", "")

            with _host.lock:
                if action == "start_pause":
                    _host.sim.start_or_pause()
                elif action == "mode":
                    _host.sim.set_mode(str(val))
                elif action == "speed":
                    _host.sim.set_time_scale(int(val))
                elif action == "detect_mode":
                    _host.sim.set_detection_mode(str(val))
                elif action == "incident_type":
                    _host.active_inc_type = str(val)
                    _host.sim.logger.log("INFO", "input", f"selected hazard type: {val.upper()}", _host.sim.sim_time)
                elif action == "explain":
                    _host.sim.toggle_explain()
                elif action == "heatmap":
                    _host.sim.toggle_heatmap()
                elif action == "demo":
                    setup_scripted_demo(_host.sim)
                elif action == "reset":
                    _host.sim.reset()
                elif action == "select_route":
                    choice = str(data.get("choice", val))
                    _host.sim.select_route(choice)
                elif action == "cycle_route":
                    _host.sim.cycle_route()

            self._send_json({"status": "ok", "state": _host.get_state()})

        elif path == "/api/drop_incident":
            lat = float(data.get("lat", 0.0))
            lon = float(data.get("lon", 0.0))
            inc_type = data.get("type", _host.active_inc_type)

            with _host.lock:
                inc_id = _host.sim.drop_incident(lat, lon, inc_type=inc_type)

            self._send_json({"status": "ok", "incident_id": inc_id, "state": _host.get_state()})

        elif path == "/api/move_incident":
            inc_id = int(data.get("id", 0))
            lat = float(data.get("lat", 0.0))
            lon = float(data.get("lon", 0.0))

            with _host.lock:
                moved = _host.sim.move_incident(inc_id, lat, lon)

            self._send_json({"status": "ok", "moved": moved, "state": _host.get_state()})

        elif path == "/api/set_endpoint":
            which = str(data.get("which", "start"))
            lat = float(data.get("lat", 0.0))
            lon = float(data.get("lon", 0.0))

            with _host.lock:
                node, dist = _host.sim.set_endpoint(which, lat, lon)

            self._send_json({"status": "ok", "which": which, "node": node, "dist_m": dist, "state": _host.get_state()})

        elif path == "/api/remove_incident":
            inc_id = data.get("id")
            lat = float(data.get("lat", 0.0))
            lon = float(data.get("lon", 0.0))

            with _host.lock:
                if inc_id is not None:
                    removed_id = int(inc_id)
                    _host.sim.incident_store.remove_incident(removed_id)
                    _host.sim.triggered_incidents.discard(removed_id)
                    _host.sim._rebuild_lookahead_index()
                    active_now = _host.sim.incident_store.get_active_incidents()
                    _host.sim.route_risks = compute_edge_risk(_host.sim.G, active_now, _host.sim.mode)
                    _host.sim.logger.log("INFO", "incident", f"#{removed_id} removed", _host.sim.sim_time)
                else:
                    removed_id = _host.sim.remove_incident_near(lat, lon, max_dist_m=120.0)

            self._send_json({"status": "ok", "removed_id": removed_id, "state": _host.get_state()})

        elif path == "/api/clear_hazards":
            with _host.lock:
                _host.sim.incident_store.clear_live_incidents()
                _host.sim.triggered_incidents.clear()
                _host.sim._rebuild_lookahead_index()
                active_now = _host.sim.incident_store.get_active_incidents()
                _host.sim.route_risks = compute_edge_risk(_host.sim.G, active_now, _host.sim.mode)
                _host.sim._calculate_initial_route()
                _host.sim.logger.log("INFO", "incident", "all live hazard zones cleared", _host.sim.sim_time)

            self._send_json({"status": "ok", "state": _host.get_state()})

        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, obj: dict) -> None:
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(payload)

    def _get_html(self) -> str:
        return r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>SafeRoute – Real-Time Hazard-Aware Navigation</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">

  <!-- Leaflet CSS & JS: Local self-hosted assets for 100% offline viva reliability -->
  <link rel="stylesheet" href="/static/leaflet.css" />
  <script src="/static/leaflet.js"></script>

  <!-- Typography -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">

  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body, html {
      width: 100%;
      height: 100%;
      overflow: hidden;
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #090d16;
      color: #f1f5f9;
      user-select: none;
    }

    #map {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      z-index: 1;
      background-color: #0b1120;
      background-image: 
        radial-gradient(rgba(56, 189, 248, 0.08) 1px, transparent 1px),
        linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
      background-size: 24px 24px, 48px 48px, 48px 48px;
    }

    /* Glassmorphism Surface Style */
    .glass {
      background: rgba(15, 23, 42, 0.88);
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
      border: 1px solid rgba(255, 255, 255, 0.12);
      box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
    }

    /* Top Left Brand Header */
    .brand-hud {
      position: absolute;
      top: 16px;
      left: 16px;
      z-index: 100;
      border-radius: 14px;
      padding: 12px 18px;
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .brand-title {
      font-size: 17px;
      font-weight: 800;
      letter-spacing: -0.3px;
      background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .brand-sub {
      font-size: 11px;
      color: #94a3b8;
      font-weight: 500;
      margin-top: 1px;
    }
    .status-badge {
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 20px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 8px currentColor;
    }
    .status-IDLE { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; }
    .status-MOVING { background: rgba(16, 185, 129, 0.2); color: #34d399; }
    .status-WARNING_1 { background: rgba(245, 158, 11, 0.25); color: #fbbf24; animation: pulse 1s infinite; }
    .status-REROUTING { background: rgba(14, 165, 233, 0.25); color: #38bdf8; }
    .status-WARNING_2 { background: rgba(16, 185, 129, 0.25); color: #10b981; }
    .status-ARRIVED { background: rgba(99, 102, 241, 0.25); color: #818cf8; }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.7; transform: scale(1.04); }
    }

    /* Warning Alert Banner (Top Center) */
    #warning-banner {
      position: absolute;
      top: 16px;
      left: 50%;
      transform: translateX(-50%) translateY(-100px);
      z-index: 200;
      padding: 12px 24px;
      border-radius: 12px;
      font-size: 14px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 12px;
      transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s;
      opacity: 0;
      pointer-events: none;
    }
    #warning-banner.visible {
      transform: translateX(-50%) translateY(0);
      opacity: 1;
    }
    .banner-w1 {
      background: linear-gradient(135deg, rgba(239, 68, 68, 0.95), rgba(185, 28, 28, 0.95));
      border: 1px solid #f87171;
      box-shadow: 0 10px 30px rgba(239, 68, 68, 0.5);
      color: #fff;
    }
    .banner-w2 {
      background: linear-gradient(135deg, rgba(16, 185, 129, 0.95), rgba(5, 150, 105, 0.95));
      border: 1px solid #34d399;
      box-shadow: 0 10px 30px rgba(16, 185, 129, 0.45);
      color: #fff;
    }

    /* Layer Switcher (Top Right) */
    .layer-hud {
      position: absolute;
      top: 16px;
      right: 470px;
      z-index: 100;
      border-radius: 12px;
      padding: 6px;
      display: flex;
      gap: 4px;
    }

    /* Right Dashboard HUD */
    .dashboard-panel {
      position: absolute;
      top: 16px;
      right: 16px;
      bottom: 96px;
      width: 440px;
      z-index: 100;
      border-radius: 18px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* Route Stats Card */
    .stats-card {
      padding: 18px 20px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    .stats-row {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 8px;
    }
    .route-dist {
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.5px;
      color: #ffffff;
    }
    .route-eta {
      font-size: 16px;
      font-weight: 700;
      color: #38bdf8;
    }
    .progress-bar {
      width: 100%;
      height: 6px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 3px;
      overflow: hidden;
      margin: 8px 0 12px;
    }
    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, #38bdf8, #10b981);
      width: 0%;
      transition: width 0.3s ease;
    }

    /* Mode comparison pills */
    .mode-compare-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-top: 10px;
    }
    .mode-compare-box {
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 10px;
      padding: 7px 10px;
      text-align: center;
    }
    .mode-compare-title { font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; }
    .mode-compare-val { font-size: 13px; font-weight: 700; color: #34d399; margin-top: 2px; }

    /* Key metrics row */
    .metrics-pills {
      display: flex;
      gap: 10px;
      margin-top: 12px;
      font-size: 12px;
      color: #cbd5e1;
    }
    .metric-item {
      background: rgba(255, 255, 255, 0.05);
      padding: 4px 10px;
      border-radius: 8px;
      font-weight: 600;
    }

    /* Live Algorithm Log Console (Large 15px font for crisp recordings) */
    .console-header {
      padding: 12px 18px 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      font-weight: 700;
      color: #94a3b8;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    .log-container {
      flex: 1;
      padding: 12px 16px;
      overflow-y: auto;
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 14.5px;
      line-height: 1.65;
      background: rgba(10, 15, 29, 0.95);
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .log-container::-webkit-scrollbar { width: 6px; }
    .log-container::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }

    .log-line {
      display: flex;
      gap: 10px;
      word-break: normal;
      overflow-wrap: break-word;
    }
    .log-badge {
      font-weight: 800;
      padding: 0 4px;
      border-radius: 3px;
      font-size: 12px;
      min-width: 54px;
      text-align: center;
      line-height: 20px;
      height: 20px;
      flex-shrink: 0;
    }
    .badge-INFO   { background: rgba(56, 189, 248, 0.2);  color: #38bdf8; }
    .badge-CALC   { background: rgba(251, 191, 36, 0.2);  color: #fbbf24; }
    .badge-ROUTE  { background: rgba(52, 211, 153, 0.2);  color: #34d399; }
    .badge-WARN   { background: rgba(251, 146, 60, 0.2);  color: #fb923c; }
    .badge-ALERT  { background: rgba(248, 113, 113, 0.25); color: #f87171; }
    .badge-ERROR  { background: rgba(244, 114, 182, 0.25); color: #f472b6; }
    .badge-STEP   { background: rgba(56, 189, 248, 0.25); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.5); }
    .badge-DONE   { background: rgba(52, 211, 153, 0.25); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.5); }
    .log-msg { color: #e2e8f0; font-weight: 500; }

    /* Routes Selection Card (P3) */
    .routes-card {
      padding: 10px 16px 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(15, 23, 42, 0.5);
    }
    .routes-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .routes-header-title {
      font-size: 11px;
      font-weight: 700;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .cycle-btn {
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 6px;
      background: rgba(56, 189, 248, 0.15);
      border: 1px solid rgba(56, 189, 248, 0.35);
      color: #38bdf8;
      cursor: pointer;
      transition: all 0.2s;
    }
    .cycle-btn:hover {
      background: rgba(56, 189, 248, 0.3);
      border-color: #38bdf8;
      transform: translateY(-1px);
    }
    .routes-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
    }
    .route-option-btn {
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 8px;
      padding: 6px 8px;
      text-align: left;
      cursor: pointer;
      transition: all 0.2s ease;
      position: relative;
    }
    .route-option-btn:hover {
      background: rgba(255, 255, 255, 0.07);
      border-color: rgba(255, 255, 255, 0.2);
    }
    .route-option-btn.active {
      background: rgba(0, 210, 255, 0.12);
      border-color: #00d2ff;
      box-shadow: 0 0 10px rgba(0, 210, 255, 0.3);
    }
    .route-option-btn.opt-fastest.active {
      background: rgba(245, 158, 11, 0.12);
      border-color: #f59e0b;
      box-shadow: 0 0 10px rgba(245, 158, 11, 0.3);
    }
    .route-option-btn.opt-safest.active {
      background: rgba(16, 185, 129, 0.12);
      border-color: #10b981;
      box-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
    }
    .route-opt-title {
      font-size: 11px;
      font-weight: 700;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2px;
    }
    .opt-fastest .route-opt-title { color: #f59e0b; }
    .opt-balanced .route-opt-title { color: #38bdf8; }
    .opt-safest .route-opt-title { color: #10b981; }
    .route-opt-stats {
      font-size: 10.5px;
      color: #e2e8f0;
      font-weight: 600;
      line-height: 1.3;
    }
    .route-opt-risk {
      font-size: 9.5px;
      color: #94a3b8;
      margin-top: 2px;
    }
    .route-opt-badge {
      font-size: 8px;
      padding: 1px 4px;
      border-radius: 4px;
      background: rgba(255,255,255,0.1);
      color: #fff;
    }

    /* Log Filter Pills & Copy button (P5) */
    .filter-pills {
      display: flex;
      gap: 4px;
      align-items: center;
    }
    .filter-pill {
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 700;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: #94a3b8;
      cursor: pointer;
      transition: all 0.15s;
    }
    .filter-pill:hover {
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
    }
    .filter-pill.active {
      background: rgba(56, 189, 248, 0.25);
      border-color: #38bdf8;
      color: #38bdf8;
    }
    .copy-btn {
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: #cbd5e1;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s;
    }
    .copy-btn:hover {
      background: rgba(255, 255, 255, 0.15);
      color: #fff;
    }

    /* Attribution Position above bottom toolbar (P8) */
    .leaflet-bottom.leaflet-left {
      bottom: 84px !important;
      left: 16px !important;
      background: rgba(10, 15, 29, 0.8) !important;
      backdrop-filter: blur(8px) !important;
      padding: 3px 10px !important;
      border-radius: 8px !important;
      font-size: 11px !important;
      color: #94a3b8 !important;
      border: 1px solid rgba(255, 255, 255, 0.08) !important;
      pointer-events: auto !important;
      z-index: 90 !important;
    }

    /* Reroute Pipeline Strip HUD */
    .pipeline-strip {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 6px 10px;
      margin-bottom: 8px;
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 8px;
      font-size: 11px;
    }
    .pipe-step {
      display: flex;
      align-items: center;
      gap: 4px;
      color: #64748b;
      transition: all 0.2s ease;
    }
    .pipe-step.active {
      color: #38bdf8;
      font-weight: 700;
      text-shadow: 0 0 8px rgba(56, 189, 248, 0.6);
    }
    .pipe-step.done {
      color: #34d399;
    }
    .pipe-num {
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.08);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 9px;
      font-weight: 800;
    }
    .pipe-step.active .pipe-num {
      background: #38bdf8;
      color: #000;
    }
    .pipe-step.done .pipe-num {
      background: #34d399;
      color: #000;
    }
    .pipe-arrow {
      color: #334155;
      font-size: 11px;
    }

    /* Bottom Human Designer Toolbar */
    .toolbar-dock {
      position: absolute;
      bottom: 16px;
      left: 16px;
      right: 16px;
      height: 64px;
      z-index: 100;
      border-radius: 20px;
      padding: 8px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .tool-group {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .group-label {
      font-size: 11px;
      font-weight: 700;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-right: 4px;
    }

    button.btn {
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: #f1f5f9;
      font-family: inherit;
      font-size: 13px;
      font-weight: 600;
      padding: 9px 14px;
      border-radius: 12px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
      outline: none;
    }
    button.btn:hover {
      background: rgba(255, 255, 255, 0.16);
      transform: translateY(-1px);
    }
    button.btn:active {
      transform: scale(0.96);
    }

    /* Primary Highlights */
    button.btn-primary {
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      border-color: #3b82f6;
      box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
    }
    button.btn-primary:hover {
      background: linear-gradient(135deg, #3b82f6, #2563eb);
    }
    button.btn-gold {
      background: linear-gradient(135deg, #d97706, #b45309);
      border-color: #f59e0b;
      box-shadow: 0 4px 14px rgba(217, 119, 6, 0.35);
    }
    button.btn-active {
      background: #38bdf8 !important;
      color: #0f172a !important;
      font-weight: 700;
      border-color: #7dd3fc !important;
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.5);
    }

    /* Hazard buttons */
    button.hazard-btn[data-type="accident"].btn-active { background: #ef4444 !important; color: #fff !important; box-shadow: 0 0 14px #ef4444; }
    button.hazard-btn[data-type="flooding"].btn-active { background: #3b82f6 !important; color: #fff !important; box-shadow: 0 0 14px #3b82f6; }
    button.hazard-btn[data-type="unsafe_area"].btn-active { background: #a855f7 !important; color: #fff !important; box-shadow: 0 0 14px #a855f7; }
    button.hazard-btn[data-type="construction"].btn-active { background: #f97316 !important; color: #fff !important; box-shadow: 0 0 14px #f97316; }
    button.hazard-btn[data-type="road_damage"].btn-active { background: #eab308 !important; color: #fff !important; box-shadow: 0 0 14px #eab308; }

    /* Map Click Instructions Toast */
    .map-hint {
      position: absolute;
      bottom: 92px;
      left: 16px;
      z-index: 100;
      font-size: 12px;
      color: #94a3b8;
      border-radius: 10px;
      padding: 6px 14px;
      pointer-events: none;
    }
  </style>
</head>
<body>

  <!-- Map Container -->
  <div id="map"></div>

  <!-- Brand HUD (Top Left) -->
  <div class="brand-hud glass">
    <div>
      <div class="brand-title">SafeRoute Simulator</div>
      <div class="brand-sub">B.Tech CSE Project (CSM216) | LPU / Chiheru</div>
    </div>
    <div id="status-pill" class="status-badge status-IDLE">
      <span class="status-dot"></span>
      <span id="status-text">IDLE</span>
    </div>
  </div>

  <!-- Layer Switcher HUD -->
  <div class="layer-hud glass">
    <button class="btn btn-active" id="layer-street" style="padding:6px 10px; font-size:12px;" onclick="setMapLayer('street')">🗺️ Street</button>
    <button class="btn" id="layer-satellite" style="padding:6px 10px; font-size:12px;" onclick="setMapLayer('satellite')">🛰️ Satellite</button>
    <button class="btn" id="layer-edges" style="padding:6px 10px; font-size:12px;" onclick="toggleGraphEdges()">🕸️ Edges (G)</button>
  </div>

  <!-- Warning Alert Banner (Top Center) -->
  <div id="warning-banner" class="glass">
    <span id="warning-icon">⚠️</span>
    <span id="warning-msg">Danger ahead detected!</span>
  </div>

  <!-- Right Dashboard & Live Console -->
  <div class="dashboard-panel glass">
    <!-- Stats Card -->
    <div class="stats-card">
      <div class="stats-row">
        <div>
          <span class="route-dist" id="route-dist-text">542 m</span>
          <span style="font-size: 13px; color: #94a3b8; margin-left: 6px;" id="traveled-text">(0 m traveled)</span>
        </div>
        <div class="route-eta" id="eta-text">ETA: 6.5 min</div>
      </div>

      <div class="progress-bar">
        <div class="progress-fill" id="progress-fill"></div>
      </div>

      <div class="mode-compare-grid">
        <div class="mode-compare-box">
          <div class="mode-compare-title">Walk (5 km/h)</div>
          <div class="mode-compare-val" id="walk-eta">6.3 min</div>
        </div>
        <div class="mode-compare-box">
          <div class="mode-compare-title">Bike (15 km/h)</div>
          <div class="mode-compare-val" id="bike-eta">2.1 min</div>
        </div>
        <div class="mode-compare-box">
          <div class="mode-compare-title">Car (OSM)</div>
          <div class="mode-compare-val" id="car-eta">1.2 min</div>
        </div>
      </div>

      <div class="metrics-pills">
        <div class="metric-item">Reroutes: <span id="reroutes-count" style="color:#38bdf8">0</span></div>
        <div class="metric-item">Avoided: <span id="avoided-count" style="color:#34d399">0</span></div>
        <div class="metric-item">Warnings: <span id="warnings-count" style="color:#fbbf24">0</span></div>
      </div>
    </div>

    <!-- Routes Card (P3: Multi-Route Alternatives) -->
    <div class="routes-card" id="routes-card">
      <div class="routes-header">
        <span class="routes-header-title">🧭 Route Options (&lambda; Aversion)</span>
        <button class="cycle-btn" onclick="sendAction('cycle_route')" title="Find another route (cycle alternatives)">
          🔄 Cycle (R)
        </button>
      </div>
      <div class="routes-grid" id="routes-grid">
        <div class="route-option-btn opt-fastest" onclick="sendAction('select_route', {choice:'fastest'})" title="Fastest route: pure travel time (&lambda;=0)">
          <div class="route-opt-title"><span>⚡ Fastest</span> <span class="route-opt-badge">&lambda;=0</span></div>
          <div class="route-opt-stats" id="opt-fastest-stats">-- m • -- min</div>
          <div class="route-opt-risk" id="opt-fastest-risk">Risk: --</div>
        </div>
        <div class="route-option-btn opt-balanced active" onclick="sendAction('select_route', {choice:'balanced'})" title="Balanced route: trade-off time vs risk (&lambda;=2)">
          <div class="route-opt-title"><span>⚖️ Balanced</span> <span class="route-opt-badge">&lambda;=2</span></div>
          <div class="route-opt-stats" id="opt-balanced-stats">528 m • 6.3 min</div>
          <div class="route-opt-risk" id="opt-balanced-risk">Risk: 0.00</div>
        </div>
        <div class="route-option-btn opt-safest" onclick="sendAction('select_route', {choice:'safest'})" title="Safest route: high risk avoidance (&lambda;=6)">
          <div class="route-opt-title"><span>🛡️ Safest</span> <span class="route-opt-badge">&lambda;=6</span></div>
          <div class="route-opt-stats" id="opt-safest-stats">-- m • -- min</div>
          <div class="route-opt-risk" id="opt-safest-risk">Risk: --</div>
        </div>
      </div>
    </div>

    <!-- Live Console Header with Filters & Copy Button (P5) -->
    <div class="console-header">
      <div style="display:flex; align-items:center; gap:6px;">
        <span>Terminal</span>
        <div class="filter-pills" id="log-filters">
          <button class="filter-pill active" onclick="setLogFilter('ALL')">ALL</button>
          <button class="filter-pill" onclick="setLogFilter('INFO')">INFO</button>
          <button class="filter-pill" onclick="setLogFilter('CALC')">CALC</button>
          <button class="filter-pill" onclick="setLogFilter('ROUTE')">ROUTE</button>
          <button class="filter-pill" onclick="setLogFilter('WARN')">WARN</button>
          <button class="filter-pill" onclick="setLogFilter('ALERT')">ALERT</button>
        </div>
      </div>
      <button class="copy-btn" id="btn-copy-log" onclick="copyLogToClipboard()" title="Copy entire console log to clipboard">
        📋 Copy
      </button>
    </div>

    <!-- Reroute Pipeline Strip HUD (1..6) -->
    <div class="pipeline-strip" id="pipeline-strip">
      <div class="pipe-step" id="pipe-1">
        <span class="pipe-num">1</span>
        <span class="pipe-name">Detect</span>
      </div>
      <div class="pipe-arrow">›</div>
      <div class="pipe-step" id="pipe-2">
        <span class="pipe-num">2</span>
        <span class="pipe-name">Weights</span>
      </div>
      <div class="pipe-arrow">›</div>
      <div class="pipe-step" id="pipe-3">
        <span class="pipe-num">3</span>
        <span class="pipe-name">Search</span>
      </div>
      <div class="pipe-arrow">›</div>
      <div class="pipe-step" id="pipe-4">
        <span class="pipe-num">4</span>
        <span class="pipe-name">Options</span>
      </div>
      <div class="pipe-arrow">›</div>
      <div class="pipe-step" id="pipe-5">
        <span class="pipe-num">5</span>
        <span class="pipe-name">Compare</span>
      </div>
      <div class="pipe-arrow">›</div>
      <div class="pipe-step" id="pipe-6">
        <span class="pipe-num">6</span>
        <span class="pipe-name">Switch</span>
      </div>
    </div>

    <!-- Log Lines -->
    <div class="log-container" id="log-container">
      <div class="log-line">
        <span class="log-badge badge-INFO">INFO</span>
        <span class="log-msg">Connecting to SafeRoute engine...</span>
      </div>
    </div>
  </div>

  <!-- Map Click & Drag Hint -->
  <div class="map-hint glass">
    💡 <b>Interactive Map:</b> Drag hazard button from toolbar or click road to drop. Drag hazard icons or START/GOAL pins to recalculate live! Right-click or ✕ to remove.
  </div>

  <!-- Bottom Dock Toolbar -->
  <div class="toolbar-dock glass">
    <!-- Playback -->
    <div class="tool-group">
      <button class="btn btn-primary" id="btn-start" onclick="sendAction('start_pause')">
        <span id="start-icon">▶</span> <span id="start-label">Start</span>
      </button>
      <button class="btn btn-gold" onclick="sendAction('demo')">
        ⭐ Scripted Demo (F5)
      </button>
      <button class="btn" style="background:rgba(239,68,68,0.2); border-color:#ef4444;" onclick="clearAllHazards()">
        🧹 Clear Hazards
      </button>
      <button class="btn" onclick="sendAction('reset')">
        ↺ Reset
      </button>
    </div>

    <!-- Mode Selector -->
    <div class="tool-group">
      <span class="group-label">Mode:</span>
      <button class="btn mode-btn btn-active" data-mode="walk" onclick="sendAction('mode', 'walk')">🚶 Walk</button>
      <button class="btn mode-btn" data-mode="bike" onclick="sendAction('mode', 'bike')">🚲 Bike</button>
      <button class="btn mode-btn" data-mode="car" onclick="sendAction('mode', 'car')">🚗 Car</button>
    </div>

    <!-- Detection Mode Toggle -->
    <div class="tool-group">
      <span class="group-label">Detect:</span>
      <button class="btn detect-btn btn-active" data-detect="instant" onclick="sendAction('detect_mode', 'instant')" title="Instant: reroute immediately when danger touches remaining route">⚡ Instant</button>
      <button class="btn detect-btn" data-detect="lookahead" onclick="sendAction('detect_mode', 'lookahead')" title="500m: warn & reroute when danger enters 500m horizon">🔭 500m</button>
    </div>

    <!-- Speed Multiplier -->
    <div class="tool-group">
      <span class="group-label">Speed:</span>
      <button class="btn speed-btn" data-speed="1" onclick="sendAction('speed', 1)">1x</button>
      <button class="btn speed-btn btn-active" data-speed="10" onclick="sendAction('speed', 10)">10x</button>
      <button class="btn speed-btn" data-speed="50" onclick="sendAction('speed', 50)">50x</button>
    </div>

    <!-- Hazard Types (Click to select, or Drag directly onto the map) -->
    <div class="tool-group">
      <span class="group-label">Hazard:</span>
      <button class="btn hazard-btn btn-active" draggable="true" data-type="accident" onclick="selectHazard('accident')" title="Drag onto map or click to select">🚨 Accident</button>
      <button class="btn hazard-btn" draggable="true" data-type="flooding" onclick="selectHazard('flooding')" title="Drag onto map or click to select">🌊 Flood</button>
      <button class="btn hazard-btn" draggable="true" data-type="unsafe_area" onclick="selectHazard('unsafe_area')" title="Drag onto map or click to select">⚠️ Unsafe</button>
      <button class="btn hazard-btn" draggable="true" data-type="construction" onclick="selectHazard('construction')" title="Drag onto map or click to select">🚧 Work</button>
      <button class="btn hazard-btn" draggable="true" data-type="road_damage" onclick="selectHazard('road_damage')" title="Drag onto map or click to select">💥 Damage</button>
    </div>

    <!-- Feature Toggles -->
    <div class="tool-group">
      <button class="btn" id="btn-explain" onclick="sendAction('explain')">🧠 Explain (L)</button>
      <button class="btn" id="btn-heatmap" onclick="sendAction('heatmap')">🔥 Heat-Map (H)</button>
    </div>
  </div>

  <script>
    // Global Frontend Error Handler (P5: transparent, visible viva debugging)
    window.onerror = function(msg, url, lineNo, colNo, error) {
      console.error('SafeRoute Frontend Error:', msg, lineNo, error);
      const term = document.getElementById('log-container');
      if (term) {
        const d = document.createElement('div');
        d.className = 'log-line';
        d.innerHTML = `<span class="log-badge badge-ALERT">FE ERR</span><span class="log-msg">${escapeHtml(String(msg))} (line ${lineNo})</span>`;
        term.appendChild(d);
      }
      return false;
    };

    // Audio synthesis with lazy creation to prevent browser autoplay blocks
    let audioCtx = null;
    function getAudioCtx() {
      if (!audioCtx) {
        try {
          audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        } catch (e) {
          audioCtx = null;
        }
      }
      return audioCtx;
    }

    function playBeep(freq = 880, type = 'sine', duration = 0.1) {
      try {
        const ctx = getAudioCtx();
        if (!ctx) return;
        if (ctx.state === 'suspended') ctx.resume();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, ctx.currentTime);
        gain.gain.setValueAtTime(0.12, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + duration);
      } catch (e) {}
    }

    // Initialize Leaflet Map centered on LPU Campus (100% self-hosted offline)
    if (typeof L === 'undefined') {
      const term = document.getElementById('log-container');
      if (term) {
        term.innerHTML = '<div class="log-line"><span class="log-badge badge-ALERT">CRITICAL</span><span class="log-msg">Leaflet library missing. Please reload.</span></div>';
      }
      throw new Error('Leaflet library is missing.');
    }

    const map = L.map('map', {
      center: [31.2551, 75.7035],
      zoom: 16,
      zoomControl: false,
      attributionControl: false
    });

    // 100% Free Official OpenStreetMap Standard Tiles (Zero API Key, Never Watermarked!)
    const osmLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    // Photorealistic Satellite Layer (Esri World Imagery, Zero API Key!)
    const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
    });

    // Base Campus Road Network Layer (100% offline visible blueprint)
    let baseRoadsLayer = null;
    let graphEdgesLayer = null;
    let cachedGraphEdges = null;

    fetch('/api/graph_edges')
      .then(r => r.json())
      .then(edges => {
        cachedGraphEdges = edges;
        baseRoadsLayer = L.polyline(edges, {
          color: '#475569',
          weight: 2,
          opacity: 0.6,
          interactive: false
        }).addTo(map);
      })
      .catch(e => console.warn('Could not load base road network:', e));

    function setMapLayer(type) {
      playBeep(600, 'sine', 0.05);
      if (type === 'satellite') {
        map.removeLayer(osmLayer);
        satelliteLayer.addTo(map);
        document.getElementById('layer-satellite').classList.add('btn-active');
        document.getElementById('layer-street').classList.remove('btn-active');
      } else {
        map.removeLayer(satelliteLayer);
        osmLayer.addTo(map);
        document.getElementById('layer-street').classList.add('btn-active');
        document.getElementById('layer-satellite').classList.remove('btn-active');
      }
    }

    function toggleGraphEdges() {
      playBeep(620, 'sine', 0.05);
      const btn = document.getElementById('layer-edges');
      if (graphEdgesLayer && map.hasLayer(graphEdgesLayer)) {
        map.removeLayer(graphEdgesLayer);
        btn.classList.remove('btn-active');
      } else {
        btn.classList.add('btn-active');
        if (cachedGraphEdges) {
          if (!graphEdgesLayer) {
            graphEdgesLayer = L.polyline(cachedGraphEdges, {
              color: '#38bdf8',
              weight: 2,
              opacity: 0.85,
              interactive: false
            });
          }
          graphEdgesLayer.addTo(map);
        } else {
          fetch('/api/graph_edges')
            .then(r => r.json())
            .then(data => {
              cachedGraphEdges = data;
              graphEdgesLayer = L.polyline(cachedGraphEdges, {
                color: '#38bdf8',
                weight: 2,
                opacity: 0.85,
                interactive: false
              });
              if (document.getElementById('layer-edges').classList.contains('btn-active')) {
                graphEdgesLayer.addTo(map);
              }
            });
        }
      }
    }

    // Attribution
    L.control.attribution({ position: 'bottomleft', prefix: false })
      .addAttribution('&copy; OpenStreetMap contributors | SafeRoute Project CSM216')
      .addTo(map);

    // Zoom control on top left below brand HUD
    L.control.zoom({ position: 'topleft' }).addTo(map);

    // Vector Layers
    let routeLayer = L.polyline([], {
      color: '#00d2ff',
      weight: 6,
      opacity: 0.95,
      lineCap: 'round',
      lineJoin: 'round'
    }).addTo(map);

    let oldRouteLayer = L.polyline([], {
      color: '#94a3b8',
      weight: 3.5,
      opacity: 0.7,
      dashArray: '6, 6'
    }).addTo(map);

    // Alternative Routes Layers (P3: Fastest=Amber, Balanced=Sky, Safest=Emerald)
    let altRouteLayers = {
      fastest: L.polyline([], {
        color: '#f59e0b',
        weight: 3.5,
        opacity: 0.85,
        dashArray: '5, 8'
      }).addTo(map),
      balanced: L.polyline([], {
        color: '#38bdf8',
        weight: 3.5,
        opacity: 0.85,
        dashArray: '5, 8'
      }).addTo(map),
      safest: L.polyline([], {
        color: '#10b981',
        weight: 3.5,
        opacity: 0.85,
        dashArray: '5, 8'
      }).addTo(map)
    };

    let incidentLayerGroup = L.layerGroup().addTo(map);

    // Walker Marker with pulsating halo
    const walkerIcon = L.divIcon({
      className: 'custom-walker',
      html: `
        <div style="position:relative; width:28px; height:28px;">
          <div style="position:absolute; width:28px; height:28px; border-radius:50%; background:rgba(56,189,248,0.35); animation:pulse 1.2s infinite;"></div>
          <div style="position:absolute; top:4px; left:4px; width:20px; height:20px; border-radius:50%; background:#0284c7; border:3px solid #ffffff; box-shadow:0 2px 8px rgba(0,0,0,0.5);"></div>
        </div>
      `,
      iconSize: [28, 28],
      iconAnchor: [14, 14]
    });
    let walkerMarker = L.marker([31.2515, 75.7047], { icon: walkerIcon }).addTo(map);

    // Start Pin Icon (Draggable)
    const startIcon = L.divIcon({
      html: `<div style="background:#10b981; color:#fff; font-weight:800; font-size:11px; padding:3px 7px; border-radius:8px; border:2px solid #fff; box-shadow:0 3px 10px rgba(0,0,0,0.4); cursor:grab;" title="Drag START location">START</div>`,
      className: '',
      iconAnchor: [24, 14]
    });

    // End Pin Icon (Draggable)
    const endIcon = L.divIcon({
      html: `<div style="background:#ef4444; color:#fff; font-weight:800; font-size:11px; padding:3px 7px; border-radius:8px; border:2px solid #fff; box-shadow:0 3px 10px rgba(0,0,0,0.4); cursor:grab;" title="Drag GOAL location">GOAL</div>`,
      className: '',
      iconAnchor: [22, 14]
    });

    let isDraggingEndpoint = false;
    let startMarker = L.marker([31.2515, 75.7047], { icon: startIcon, draggable: true, title: "Drag START location" }).addTo(map);
    let endMarker = L.marker([31.2559, 75.7042], { icon: endIcon, draggable: true, title: "Drag GOAL location" }).addTo(map);

    startMarker.on('dragstart', () => { isDraggingEndpoint = true; });
    startMarker.on('dragend', (e) => {
      isDraggingEndpoint = false;
      const pos = e.target.getLatLng();
      playBeep(700, 'sine', 0.08);
      fetch('/api/set_endpoint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ which: 'start', lat: pos.lat, lon: pos.lng })
      }).then(r => r.json()).then(data => updateUI(data.state));
    });

    endMarker.on('dragstart', () => { isDraggingEndpoint = true; });
    endMarker.on('dragend', (e) => {
      isDraggingEndpoint = false;
      const pos = e.target.getLatLng();
      playBeep(700, 'sine', 0.08);
      fetch('/api/set_endpoint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ which: 'end', lat: pos.lat, lon: pos.lng })
      }).then(r => r.json()).then(data => updateUI(data.state));
    });

    // Colors & Emojis by Incident Type
    const HAZARD_CONFIG = {
      accident:     { color: '#ef4444', emoji: '🚨' },
      flooding:     { color: '#3b82f6', emoji: '🌊' },
      unsafe_area:  { color: '#a855f7', emoji: '⚠️' },
      construction: { color: '#f97316', emoji: '🚧' },
      road_damage:  { color: '#eab308', emoji: '💥' }
    };

    let selectedHazardType = 'accident';
    let draggedHazardType = null;
    let isDraggingIncident = false;

    // Ghost preview circle when dragging a hazard button onto the map
    const previewCircle = L.circle([0, 0], {
      radius: 120,
      color: '#ef4444',
      weight: 2,
      dashArray: '6, 6',
      fillColor: '#ef4444',
      fillOpacity: 0.28,
      interactive: false
    });

    // HTML5 Drag-and-Drop from toolbar hazard buttons onto the map
    document.querySelectorAll('.hazard-btn').forEach(btn => {
      btn.addEventListener('dragstart', (e) => {
        draggedHazardType = btn.dataset.type;
        e.dataTransfer.setData('text/plain', draggedHazardType);
        e.dataTransfer.effectAllowed = 'copy';
        const conf = HAZARD_CONFIG[draggedHazardType] || { color: '#ef4444' };
        previewCircle.setStyle({ color: conf.color, fillColor: conf.color });
      });
      btn.addEventListener('dragend', () => {
        if (map.hasLayer(previewCircle)) map.removeLayer(previewCircle);
        draggedHazardType = null;
      });
    });

    const mapContainer = document.getElementById('map');
    mapContainer.addEventListener('dragenter', (e) => {
      e.preventDefault();
      if (!map.hasLayer(previewCircle)) previewCircle.addTo(map);
    });

    mapContainer.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      const rect = mapContainer.getBoundingClientRect();
      const pt = L.point(e.clientX - rect.left, e.clientY - rect.top);
      const latlng = map.containerPointToLatLng(pt);
      previewCircle.setLatLng(latlng);
      if (!map.hasLayer(previewCircle)) previewCircle.addTo(map);
    });

    mapContainer.addEventListener('dragleave', (e) => {
      if (e.relatedTarget && !mapContainer.contains(e.relatedTarget)) {
        if (map.hasLayer(previewCircle)) map.removeLayer(previewCircle);
      }
    });

    mapContainer.addEventListener('drop', (e) => {
      e.preventDefault();
      if (map.hasLayer(previewCircle)) map.removeLayer(previewCircle);
      const hType = e.dataTransfer.getData('text/plain') || draggedHazardType || selectedHazardType;
      const rect = mapContainer.getBoundingClientRect();
      const pt = L.point(e.clientX - rect.left, e.clientY - rect.top);
      const latlng = map.containerPointToLatLng(pt);
      playBeep(640, 'triangle', 0.08);
      fetch('/api/drop_incident', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lat: latlng.lat,
          lon: latlng.lng,
          type: hType
        })
      }).then(r => r.json()).then(data => updateUI(data.state));
    });

    // Click on Map to Drop Hazard (Fallback)
    map.on('click', function(e) {
      if (isDraggingIncident || isDraggingEndpoint) return;
      playBeep(640, 'triangle', 0.08);
      fetch('/api/drop_incident', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lat: e.latlng.lat,
          lon: e.latlng.lng,
          type: selectedHazardType
        })
      }).then(r => r.json()).then(data => updateUI(data.state));
    });

    function selectHazard(type) {
      selectedHazardType = type;
      playBeep(520, 'sine', 0.05);
      document.querySelectorAll('.hazard-btn').forEach(b => {
        b.classList.toggle('btn-active', b.dataset.type === type);
      });
      sendAction('incident_type', type);
    }

    function clearAllHazards() {
      playBeep(440, 'sine', 0.1);
      fetch('/api/clear_hazards', { method: 'POST' })
        .then(r => r.json())
        .then(data => updateUI(data.state));
    }

    function removeIncidentById(id, lat, lon, ev) {
      if (ev) ev.stopPropagation();
      playBeep(400, 'sine', 0.08);
      fetch('/api/remove_incident', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: id, lat: lat, lon: lon })
      }).then(r => r.json()).then(data => updateUI(data.state));
    }

    function sendAction(action, val = '') {
      playBeep(700, 'sine', 0.06);
      const payload = (typeof val === 'object' && val !== null)
        ? Object.assign({ action: action }, val)
        : { action: action, val: val };
      fetch('/api/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(r => r.json()).then(data => updateUI(data.state));
    }

    // Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Space') { e.preventDefault(); sendAction('start_pause'); }
      else if (e.code === 'Digit1') sendAction('mode', 'walk');
      else if (e.code === 'Digit2') sendAction('mode', 'bike');
      else if (e.code === 'Digit3') sendAction('mode', 'car');
      else if (e.code === 'KeyR') sendAction('cycle_route');
      else if (e.code === 'KeyQ') selectHazard('accident');
      else if (e.code === 'KeyW') selectHazard('flooding');
      else if (e.code === 'KeyE') selectHazard('unsafe_area');
      else if (e.code === 'KeyR') selectHazard('construction');
      else if (e.code === 'KeyT') selectHazard('road_damage');
      else if (e.code === 'KeyL') sendAction('explain');
      else if (e.code === 'KeyH') sendAction('heatmap');
      else if (e.code === 'KeyG') toggleGraphEdges();
      else if (e.code === 'KeyF5') { e.preventDefault(); sendAction('demo'); }
      else if (e.code === 'Escape') sendAction('reset');
    });

    let lastWarningState = '';
    let existingIncidentMarkers = {};

    let lastIncidentsJson = '';
    let lastLogsKey = '';

    // Update UI Elements with server state
    function updateUI(s) {
      if (!s) return;

      // 1. Status Badge
      const statusPill = document.getElementById('status-pill');
      statusPill.className = 'status-badge status-' + s.state;
      let displayStatus = s.state;
      if (s.is_paused) displayStatus += ' (PAUSED)';
      document.getElementById('status-text').innerText = displayStatus;

      // 2. Playback Button
      const isRunning = (s.state === 'MOVING' || s.state === 'WARNING_2') && !s.is_paused;
      document.getElementById('start-icon').innerText = isRunning ? '⏸' : '▶';
      document.getElementById('start-label').innerText = isRunning ? 'Pause' : 'Start';
      document.getElementById('btn-start').classList.toggle('btn-primary', !isRunning);
      document.getElementById('btn-start').classList.toggle('btn-active', isRunning);

      // 3. Mode buttons
      document.querySelectorAll('.mode-btn').forEach(b => {
        b.classList.toggle('btn-active', b.dataset.mode === s.mode);
      });

      // 3b. Detection mode buttons
      document.querySelectorAll('.detect-btn').forEach(b => {
        b.classList.toggle('btn-active', b.dataset.detect === (s.detection_mode || 'instant'));
      });

      // 3c. Pipeline strip indicators (1..6)
      const pStep = s.pipeline_step || 0;
      for (let i = 1; i <= 6; i++) {
        const el = document.getElementById('pipe-' + i);
        if (el) {
          el.classList.toggle('active', pStep === i);
          el.classList.toggle('done', pStep > i || (pStep === 6 && i <= 6));
        }
      }

      // 4. Speed buttons
      document.querySelectorAll('.speed-btn').forEach(b => {
        b.classList.toggle('btn-active', parseInt(b.dataset.speed) === s.speed_scale);
      });

      // 5. Toggles
      document.getElementById('btn-explain').classList.toggle('btn-active', s.explain_mode);
      document.getElementById('btn-heatmap').classList.toggle('btn-active', s.show_heatmap);

      // 6. Stats Card
      const routeLen = s.route_stats.length_m || 0;
      const traveled = s.walker ? s.walker.distance_m : 0;
      const etaMin = s.route_stats.eta_minutes || 0;
      document.getElementById('route-dist-text').innerText = `${routeLen.toFixed(0)} m`;
      document.getElementById('traveled-text').innerText = `(${traveled.toFixed(0)} m traveled)`;
      document.getElementById('eta-text').innerText = `ETA: ${etaMin.toFixed(1)} min`;

      const pct = routeLen > 0 ? Math.min(100, (traveled / routeLen) * 100) : 0;
      document.getElementById('progress-fill').style.width = pct + '%';

      // Multi-modal ETAs (P6: clear unambiguous units)
      if (s.all_mode_etas) {
        document.getElementById('walk-eta').innerText = (s.all_mode_etas.walk?.eta_minutes || 0).toFixed(1) + ' min';
        document.getElementById('bike-eta').innerText = (s.all_mode_etas.bike?.eta_minutes || 0).toFixed(1) + ' min';
        document.getElementById('car-eta').innerText = (s.all_mode_etas.car?.eta_minutes || 0).toFixed(1) + ' min';
      }

      // Metrics
      document.getElementById('reroutes-count').innerText = s.reroute_count || 0;
      document.getElementById('avoided-count').innerText = s.incidents_avoided || 0;
      document.getElementById('warnings-count').innerText = s.warnings_count || 0;

      // 6b. Route Alternatives (P3: Fastest, Balanced, Safest)
      if (s.route_alternatives) {
        ['fastest', 'balanced', 'safest'].forEach(k => {
          const alt = s.route_alternatives[k];
          const statsEl = document.getElementById(`opt-${k}-stats`);
          const riskEl = document.getElementById(`opt-${k}-risk`);
          const btnEl = document.querySelector(`.opt-${k}`);
          if (alt) {
            if (statsEl) statsEl.innerText = `${alt.length_m} m • ${alt.eta_minutes} min`;
            if (riskEl) {
              const dupText = alt.is_duplicate ? ' (shared path)' : '';
              riskEl.innerText = `Risk: ${alt.risk.toFixed(2)}${dupText}`;
            }
            if (btnEl) btnEl.classList.toggle('active', !!alt.is_active);

            // Render alternative candidate paths as thin dashed lines
            if (alt.is_active || alt.is_duplicate || !alt.polyline || alt.polyline.length === 0) {
              altRouteLayers[k].setLatLngs([]);
            } else {
              altRouteLayers[k].setLatLngs(alt.polyline);
            }
          }
        });
      }

      // 7. Warning Banners
      const banner = document.getElementById('warning-banner');
      if (s.warning_1_banner) {
        banner.className = 'glass banner-w1 visible';
        document.getElementById('warning-icon').innerText = '🚨';
        document.getElementById('warning-msg').innerText = s.warning_1_banner;
        if (lastWarningState !== 'w1') {
          playBeep(880, 'square', 0.25);
          lastWarningState = 'w1';
        }
      } else if (s.warning_2_banner) {
        banner.className = 'glass banner-w2 visible';
        document.getElementById('warning-icon').innerText = '🛡️';
        document.getElementById('warning-msg').innerText = s.warning_2_banner;
        if (lastWarningState !== 'w2') {
          playBeep(587, 'sine', 0.2);
          lastWarningState = 'w2';
        }
      } else {
        banner.classList.remove('visible');
        lastWarningState = '';
      }

      // 8. Update Routes
      if (s.current_route && s.current_route.length > 0) {
        routeLayer.setLatLngs(s.current_route);
      } else {
        routeLayer.setLatLngs([]);
      }

      if (s.previous_route && s.previous_route.length > 0) {
        oldRouteLayer.setLatLngs(s.previous_route);
      } else {
        oldRouteLayer.setLatLngs([]);
      }

      // 9. Update Walker Marker
      if (s.walker) {
        walkerMarker.setLatLng([s.walker.lat, s.walker.lon]);
        walkerMarker.setOpacity(1);
      } else {
        walkerMarker.setOpacity(0);
      }

      // 10. Markers (draggable START & GOAL)
      if (!isDraggingEndpoint) {
        if (s.start_latlon) startMarker.setLatLng(s.start_latlon);
        if (s.end_latlon) endMarker.setLatLng(s.end_latlon);
      }

      // 11. Draggable Danger Zones
      if (!isDraggingIncident) {
        const incJson = JSON.stringify(s.incidents || []);
        if (incJson !== lastIncidentsJson) {
          lastIncidentsJson = incJson;
          incidentLayerGroup.clearLayers();
          if (s.incidents) {
            s.incidents.forEach(inc => {
              const conf = HAZARD_CONFIG[inc.type] || { color: '#ef4444', emoji: '🚨' };

              // Danger radius circle (P7: historical simulated incidents are dashed lighter, live are solid)
              const isHistorical = (inc.source === 'historical');
              const circle = L.circle([inc.lat, inc.lon], {
                radius: inc.radius_m,
                color: conf.color,
                weight: isHistorical ? 1.5 : 2.5,
                dashArray: isHistorical ? '5, 6' : null,
                fillColor: conf.color,
                fillOpacity: isHistorical ? 0.18 : 0.35,
                interactive: false
              }).addTo(incidentLayerGroup);

              // Draggable center badge with emoji, quick-remove '✕' badge, and simulated/live label
              const hazardIcon = L.divIcon({
                className: '',
                html: `
                  <div style="position:relative; width:34px; height:34px;">
                    <div style="width:34px; height:34px; border-radius:50%; background:${conf.color}; border:3px solid #ffffff; box-shadow:0 4px 14px rgba(0,0,0,0.5); display:flex; align-items:center; justify-content:center; font-size:16px; cursor:grab;" title="Drag hazard onto road to test look-ahead reroute">
                      ${conf.emoji}
                    </div>
                    <div onclick="removeIncidentById(${inc.id}, ${inc.lat}, ${inc.lon}, event)" style="position:absolute; top:-5px; right:-5px; width:16px; height:16px; border-radius:50%; background:#ef4444; color:#fff; font-size:10px; font-weight:800; line-height:14px; text-align:center; border:1.5px solid #fff; cursor:pointer; box-shadow:0 2px 5px rgba(0,0,0,0.5);" title="Remove hazard">✕</div>
                    <div style="position:absolute; bottom:-14px; left:50%; transform:translateX(-50%); font-size:8.5px; font-weight:700; background:rgba(10,15,29,0.85); padding:1px 5px; border-radius:4px; color:${isHistorical ? '#94a3b8' : '#f87171'}; border:1px solid rgba(255,255,255,0.1); white-space:nowrap; pointer-events:none;">${isHistorical ? 'simulated' : 'live'}</div>
                  </div>
                `,
                iconSize: [34, 34],
                iconAnchor: [17, 17]
              });

              const marker = L.marker([inc.lat, inc.lon], {
                icon: hazardIcon,
                draggable: true,
                title: 'Drag hazard onto road to test look-ahead reroute'
              }).addTo(incidentLayerGroup);

              // While dragging: smoothly update circle position locally (no routing on mouse-move)
              marker.on('dragstart', () => { isDraggingIncident = true; });
              marker.on('drag', (e) => {
                circle.setLatLng(e.target.getLatLng());
              });

              // On drag end: send new position to backend, immediately trigger look-ahead and reroute!
              marker.on('dragend', (e) => {
                isDraggingIncident = false;
                const pos = e.target.getLatLng();
                playBeep(740, 'triangle', 0.1);
                fetch('/api/move_incident', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ id: inc.id, lat: pos.lat, lon: pos.lng })
                }).then(r => r.json()).then(data => updateUI(data.state));
              });

              // Right click marker to remove
              marker.on('contextmenu', (e) => {
                L.DomEvent.stopPropagation(e);
                playBeep(400, 'sine', 0.08);
                fetch('/api/remove_incident', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ lat: inc.lat, lon: inc.lon })
                }).then(r => r.json()).then(data => updateUI(data.state));
              });
            });
          }
        }
      }

      // 12. Update Live Log Console (P5: clean non-repeating levels & filter support)
      const logsKey = (s.logs && s.logs.length) ? `${s.logs.length}:${s.logs[s.logs.length - 1].text}` : '';
      if (logsKey !== lastLogsKey) {
        lastLogsKey = logsKey;
        cachedLogs = s.logs || [];
        renderFilteredLogs();
      }
    }

    let currentLogFilter = 'ALL';
    let cachedLogs = [];

    function setLogFilter(lvl) {
      currentLogFilter = lvl;
      document.querySelectorAll('.filter-pill').forEach(b => {
        b.classList.toggle('active', b.innerText === lvl);
      });
      renderFilteredLogs();
    }

    function renderFilteredLogs() {
      const logContainer = document.getElementById('log-container');
      if (!logContainer) return;
      let filtered = cachedLogs;
      if (currentLogFilter !== 'ALL') {
        filtered = cachedLogs.filter(l => l.level.startsWith(currentLogFilter));
      }
      logContainer.innerHTML = filtered.map(l => {
        const badgeClass = l.level.startsWith('STEP') ? 'badge-STEP' : 'badge-' + l.level;
        // Strip duplicate level word from start of text so it's not repeated
        const cleanText = l.text.replace(/^(\[\d{2}:\d{2}\.\d\])\s+[A-Z0-9\/\-]+\s+/, '$1 ');
        return `
          <div class="log-line">
            <span class="log-badge ${badgeClass}">${escapeHtml(l.level)}</span>
            <span class="log-msg">${escapeHtml(cleanText)}</span>
          </div>
        `;
      }).join('');
      logContainer.scrollTop = logContainer.scrollHeight;
    }

    function copyLogToClipboard() {
      const text = cachedLogs.map(l => l.text).join('\n');
      navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById('btn-copy-log');
        if (btn) {
          btn.innerText = '✓ Copied!';
          setTimeout(() => { btn.innerText = '📋 Copy'; }, 1500);
        }
      });
    }

    function escapeHtml(text) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
      return text.replace(/[&<>"']/g, m => map[m]);
    }

    // Real-time polling loop (every 120ms = ~8 Hz)
    function pollState() {
      fetch('/api/state')
        .then(r => r.json())
        .then(data => {
          updateUI(data);
          setTimeout(pollState, 120);
        })
        .catch(err => {
          setTimeout(pollState, 500);
        });
    }

    pollState();
  </script>
</body>
</html>
"""


def start_server(port: int = 8000, mode: str = "walk", speed: int = 10) -> None:
    """Start the simulation engine and HTTP server on localhost:port."""
    global _host
    print(f"\n=======================================================")
    print(f" SafeRoute Localhost Simulator Server")
    print(f" URL: http://localhost:{port}")
    print(f" Press Ctrl+C in terminal to stop.")
    print(f"=======================================================\n")

    _host = SimulationHost(mode=mode, speed=speed)

    # Start background tick loop
    t = threading.Thread(target=_host.loop, daemon=True)
    t.start()

    server = HTTPServer(("0.0.0.0", port), SafeRouteWebHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down SafeRoute web server...")
    finally:
        _host.running = False
        server.server_close()


if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    start_server(port=port)
