"""
ui/map_renderer.py – Draws the OpenStreetMap basemap, road network, routes,
danger zones, markers, and walker.

Coordinate Conversion:
  - Basemap extent is in EPSG:3857 (Web Mercator metres).
  - Graph nodes and incidents are in WGS84 (lat, lon) and projected UTM (x, y).
  - Conversion from (lat, lon) to EPSG:3857 to pixel guarantees exact 1:1 alignment
    between the road network vector lines and the underlying raster map.
"""

import json
import math
import os
from pathlib import Path
from typing import Any, Optional

import networkx as nx
import pygame
import pyproj

from config import (
    INCIDENT_TYPES,
    MAP_PANEL_WIDTH_FRAC,
    WINDOW_SIZE,
)

# Color palette for rendering
COLOR_BG = (28, 32, 40)
COLOR_ROAD_DEFAULT = (140, 148, 160)
COLOR_ROAD_OUTLINE = (100, 108, 120)
COLOR_ROUTE_ACTIVE = (30, 144, 255)       # Dodger blue
COLOR_ROUTE_OLD = (220, 80, 50, 140)      # Translucent red
COLOR_WALKER = (255, 215, 0)              # Gold
COLOR_WALKER_OUTLINE = (20, 20, 20)
COLOR_START_NODE = (46, 204, 113)         # Green
COLOR_END_NODE = (231, 76, 60)            # Red
COLOR_TEXT = (240, 240, 240)
COLOR_ATTRIBUTION = (160, 165, 175)

# Zone colors by incident type (RGBA) – Modern Tailwind / Apple palette
INCIDENT_COLORS = {
    "accident":     {"fill": (239, 68, 68, 75),   "border": (239, 68, 68, 240)},   # Vibrant Red
    "flooding":     {"fill": (59, 130, 246, 75),  "border": (59, 130, 246, 240)},  # Electric Blue
    "unsafe_area":  {"fill": (168, 85, 247, 75),  "border": (168, 85, 247, 240)},  # Purple
    "construction": {"fill": (249, 115, 22, 75),  "border": (249, 115, 22, 240)},  # Bright Orange
    "road_damage":  {"fill": (234, 179, 8, 75),   "border": (234, 179, 8, 240)},   # Warning Yellow
}


class MapRenderer:
    """Renders map, roads, routes, danger zones and walker onto a Pygame surface."""

    def __init__(self, viewport_rect: Optional[pygame.Rect] = None):
        """Initialize the map renderer.

        Args:
            viewport_rect: Bounding rect for the map portion of the window.
                           Defaults to the left 65% of WINDOW_SIZE.
        """
        if viewport_rect is None:
            w = int(WINDOW_SIZE[0] * MAP_PANEL_WIDTH_FRAC)
            h = WINDOW_SIZE[1]
            self.viewport_rect = pygame.Rect(0, 0, w, h)
        else:
            self.viewport_rect = viewport_rect

        self.project_root = Path(__file__).resolve().parent.parent
        self.cache_dir = self.project_root / "data" / "cache"

        # Pyproj transformers
        self.transformer_4326_to_3857 = pyproj.Transformer.from_crs(
            "EPSG:4326", "EPSG:3857", always_xy=True
        )
        self.transformer_3857_to_4326 = pyproj.Transformer.from_crs(
            "EPSG:3857", "EPSG:4326", always_xy=True
        )

        # Basemap attributes
        self.basemap_surface: Optional[pygame.Surface] = None
        self.basemap_meta: Optional[dict[str, Any]] = None
        self.xmin = 0.0
        self.xmax = 0.0
        self.ymin = 0.0
        self.ymax = 0.0
        self.img_w = 1280
        self.img_h = 1280

        # View transform (scaling and centering)
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.default_scale = 1.0
        self.default_offset_x = 0.0
        self.default_offset_y = 0.0
        self.raw_surface: Optional[pygame.Surface] = None

        # Pre-calculated node pixel positions cache: node_id -> (px, py)
        self._node_pixel_cache: dict[int, tuple[int, int]] = {}

        # Fonts (initialized lazily)
        self.font_small: Optional[pygame.font.Font] = None
        self.font_bold: Optional[pygame.font.Font] = None

        self._load_basemap()

    def _load_basemap(self) -> None:
        """Load the pre-rendered basemap image and its bounding box metadata."""
        png_path = self.cache_dir / "basemap.png"
        meta_path = self.cache_dir / "basemap_meta.json"

        if png_path.exists() and meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    self.basemap_meta = json.load(f)

                self.xmin, self.xmax, self.ymin, self.ymax = self.basemap_meta["extent"]
                self.img_w = self.basemap_meta["width"]
                self.img_h = self.basemap_meta["height"]

                self.raw_surface = pygame.image.load(str(png_path))
                self.img_w, self.img_h = self.raw_surface.get_size()

                # Calculate uniform scaling to fit viewport
                vw = self.viewport_rect.width
                vh = self.viewport_rect.height
                self.scale = min(vw / self.img_w, vh / self.img_h)
                self.default_scale = self.scale

                scaled_w = int(self.img_w * self.scale)
                scaled_h = int(self.img_h * self.scale)
                self.basemap_surface = pygame.transform.smoothscale(self.raw_surface, (scaled_w, scaled_h))

                # Center the map within the viewport
                self.offset_x = self.viewport_rect.x + (vw - scaled_w) / 2.0
                self.offset_y = self.viewport_rect.y + (vh - scaled_h) / 2.0
                self.default_offset_x = self.offset_x
                self.default_offset_y = self.offset_y
            except Exception as e:
                print(f"[WARN] Failed to load basemap image: {e}")
                self.basemap_surface = None
        else:
            self.basemap_surface = None

    def zoom(self, factor: float, center_px: Optional[tuple[int, int]] = None) -> None:
        """Zoom the map in or out smoothly, pivoted around a center pixel coordinate."""
        new_scale = max(0.4, min(10.0, self.scale * factor))
        if math.isclose(new_scale, self.scale, rel_tol=1e-4):
            return

        cx, cy = center_px if center_px else (self.viewport_rect.centerx, self.viewport_rect.centery)

        # Keep the point under cursor invariant
        self.offset_x = cx - (cx - self.offset_x) * (new_scale / self.scale)
        self.offset_y = cy - (cy - self.offset_y) * (new_scale / self.scale)
        self.scale = new_scale

        self._node_pixel_cache.clear()

        # Update scaled basemap raster
        if self.raw_surface is not None:
            sw = max(10, int(self.img_w * self.scale))
            sh = max(10, int(self.img_h * self.scale))
            self.basemap_surface = pygame.transform.smoothscale(self.raw_surface, (sw, sh))

    def pan(self, dx: float, dy: float) -> None:
        """Pan the map view by pixel offsets (dx, dy)."""
        self.offset_x += dx
        self.offset_y += dy
        self._node_pixel_cache.clear()

    def reset_view(self) -> None:
        """Reset zoom scale and pan offsets back to default extent."""
        self.scale = self.default_scale
        self.offset_x = self.default_offset_x
        self.offset_y = self.default_offset_y
        self._node_pixel_cache.clear()
        if self.raw_surface is not None:
            sw = int(self.img_w * self.scale)
            sh = int(self.img_h * self.scale)
            self.basemap_surface = pygame.transform.smoothscale(self.raw_surface, (sw, sh))

    def _ensure_fonts(self) -> None:
        """Initialize pygame fonts if not already initialized."""
        if self.font_small is None:
            if not pygame.font.get_init():
                pygame.font.init()
            self.font_small = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 13)
            self.font_bold = pygame.font.SysFont("Segoe UI, Arial, sans-serif", 16, bold=True)

    def latlon_to_pixel(self, lat: float, lon: float) -> tuple[int, int]:
        """Convert WGS84 (lat, lon) to screen pixel coordinates.

        Formula:
          X3857, Y3857 = transform(lon, lat)
          img_px = (X3857 - xmin) / (xmax - xmin) * img_w
          img_py = (ymax - Y3857) / (ymax - ymin) * img_h
          screen_px = offset_x + img_px * scale
          screen_py = offset_y + img_py * scale
        """
        x3857, y3857 = self.transformer_4326_to_3857.transform(lon, lat)
        return self.webmercator_to_pixel(x3857, y3857)

    def webmercator_to_pixel(self, x3857: float, y3857: float) -> tuple[int, int]:
        """Convert EPSG:3857 coordinates to screen pixel coordinates."""
        span_x = self.xmax - self.xmin
        span_y = self.ymax - self.ymin
        if span_x <= 0 or span_y <= 0:
            return 0, 0

        img_px = (x3857 - self.xmin) / span_x * self.img_w
        img_py = (self.ymax - y3857) / span_y * self.img_h

        screen_px = int(round(self.offset_x + img_px * self.scale))
        screen_py = int(round(self.offset_y + img_py * self.scale))
        return screen_px, screen_py

    def pixel_to_latlon(self, screen_px: int, screen_py: int) -> tuple[float, float]:
        """Convert screen pixel coordinates back to WGS84 (lat, lon)."""
        if self.scale <= 0:
            return 0.0, 0.0

        img_px = (screen_px - self.offset_x) / self.scale
        img_py = (screen_py - self.offset_y) / self.scale

        span_x = self.xmax - self.xmin
        span_y = self.ymax - self.ymin

        x3857 = self.xmin + (img_px / self.img_w) * span_x
        y3857 = self.ymax - (img_py / self.img_h) * span_y

        lon, lat = self.transformer_3857_to_4326.transform(x3857, y3857)
        return float(lat), float(lon)

    def metres_to_pixels(self, dist_m: float, lat: float = 31.2551) -> int:
        """Convert real-world distance in metres to screen pixels.

        Web Mercator distorts distance by 1 / cos(latitude).
        """
        span_x = self.xmax - self.xmin
        if span_x <= 0:
            return 1
        # 1 metre in EPSG:3857 ~ 1 / cos(radians(lat))
        mercator_m = dist_m / math.cos(math.radians(lat))
        px = mercator_m * (self.img_w / span_x) * self.scale
        return max(1, int(round(px)))

    def draw_basemap(self, surface: pygame.Surface) -> None:
        """Draw the basemap image onto the surface, or fallback background if missing."""
        if self.basemap_surface is not None:
            # Clip drawing to viewport
            surface.set_clip(self.viewport_rect)
            surface.fill(COLOR_BG, self.viewport_rect)
            surface.blit(self.basemap_surface, (self.offset_x, self.offset_y))
            surface.set_clip(None)
        else:
            surface.fill(COLOR_BG, self.viewport_rect)
            self._ensure_fonts()
            if self.font_small:
                txt = self.font_small.render(
                    "WARN: basemap missing - drawing road network only", True, (240, 160, 40)
                )
                surface.blit(txt, (self.viewport_rect.x + 20, self.viewport_rect.y + 20))

    def draw_road_network(self, surface: pygame.Surface, G: nx.MultiDiGraph, edge_risks: Optional[dict] = None) -> None:
        """Draw street network edges overlaid on top of the basemap.

        When heat-map is OFF and basemap is loaded, skips redundant raw lines
        so the crisp OpenStreetMap cartography remains clean and unobscured.
        When heat-map is ON, highlights high-risk road corridors with glowing colors.
        """
        # If basemap is present and heat-map is off, let the crisp cartography shine
        if self.basemap_surface is not None and not edge_risks:
            return

        surface.set_clip(self.viewport_rect)

        # Cache node pixel locations if not cached
        for n, data in G.nodes(data=True):
            if n not in self._node_pixel_cache:
                lat = data.get("lat", data.get("y"))
                lon = data.get("lon", data.get("x"))
                self._node_pixel_cache[n] = self.latlon_to_pixel(lat, lon)

        # Draw risk-highlighted edges
        for u, v, k, data in G.edges(keys=True, data=True):
            # Skip boundary clip artifact edges (> 450 m straight lines)
            if float(data.get("length", 0.0)) > 450.0:
                continue

            p1 = self._node_pixel_cache.get(u)
            p2 = self._node_pixel_cache.get(v)
            if not p1 or not p2:
                continue

            # Determine color based on risk if heat-map is active
            if edge_risks and (u, v, k) in edge_risks:
                risk = edge_risks[(u, v, k)]
                if risk <= 0.05:
                    continue  # Safe road, no overlay clutter
                elif risk < 0.5:
                    color = (250, 204, 21)   # Radiant yellow (#facc15)
                    width = 3
                elif risk < 1.5:
                    color = (249, 115, 22)   # Orange (#f97316)
                    width = 4
                else:
                    color = (239, 68, 68)    # High risk crimson (#ef4444)
                    width = 5
            elif self.basemap_surface is None:
                color = COLOR_ROAD_DEFAULT
                width = 2
            else:
                continue

            pygame.draw.line(surface, color, p1, p2, width)

        surface.set_clip(None)

    def draw_route(
        self,
        surface: pygame.Surface,
        G: nx.MultiDiGraph,
        path: list[int],
        is_active: bool = True,
    ) -> None:
        """Draw a planned route path along the road network with Apple Maps style glow."""
        if len(path) < 2:
            return

        surface.set_clip(self.viewport_rect)

        points = []
        for node in path:
            if node in self._node_pixel_cache:
                points.append(self._node_pixel_cache[node])
            elif node in G.nodes:
                lat = G.nodes[node].get("lat", G.nodes[node]["y"])
                lon = G.nodes[node].get("lon", G.nodes[node]["x"])
                pt = self.latlon_to_pixel(lat, lon)
                self._node_pixel_cache[node] = pt
                points.append(pt)

        if len(points) >= 2:
            if is_active:
                # 1. Dark outline shadow
                pygame.draw.lines(surface, (15, 23, 42), False, points, 8)
                # 2. Electric cyan/blue main route (Apple Maps / Tesla navigation style)
                pygame.draw.lines(surface, (0, 168, 255), False, points, 5)
            else:
                # Old detour route (translucent dashed/crimson)
                pygame.draw.lines(surface, (239, 68, 68, 160), False, points, 4)

        surface.set_clip(None)

    def draw_incident(self, surface: pygame.Surface, incident: Any) -> None:
        """Draw a circular danger zone with semi-transparent fill and border.

        Args:
            surface: Target Pygame surface.
            incident: Incident object or dict with lat, lon, radius_m, type.
        """
        if hasattr(incident, "lat"):
            lat = incident.lat
            lon = incident.lon
            radius_m = getattr(incident, "radius_m", 100.0)
            inc_type = getattr(incident, "type", "accident")
        elif isinstance(incident, dict):
            lat = incident.get("lat", 0.0)
            lon = incident.get("lon", 0.0)
            radius_m = incident.get("radius_m", 100.0)
            inc_type = incident.get("type", "accident")
        else:
            lat = getattr(incident, "lat", 0.0)
            lon = getattr(incident, "lon", 0.0)
            radius_m = getattr(incident, "radius_m", 100.0)
            inc_type = getattr(incident, "type", "accident")

        cx, cy = self.latlon_to_pixel(lat, lon)
        r_px = self.metres_to_pixels(radius_m, lat)

        color_cfg = INCIDENT_COLORS.get(inc_type, INCIDENT_COLORS["accident"])
        fill_color = color_cfg["fill"]
        border_color = color_cfg["border"]

        # Create alpha surface for transparency
        zone_surface = pygame.Surface((r_px * 2 + 4, r_px * 2 + 4), pygame.SRCALPHA)
        center = (r_px + 2, r_px + 2)

        # Draw translucent filled circle
        pygame.draw.circle(zone_surface, fill_color, center, r_px)
        # Draw solid perimeter
        pygame.draw.circle(zone_surface, border_color, center, r_px, 2)
        # Draw center icon / dot
        pygame.draw.circle(zone_surface, border_color[:3], center, 5)

        surface.set_clip(self.viewport_rect)
        surface.blit(zone_surface, (cx - r_px - 2, cy - r_px - 2))
        surface.set_clip(None)

    def draw_walker(
        self,
        surface: pygame.Surface,
        lat: float,
        lon: float,
        heading_deg: Optional[float] = None,
    ) -> None:
        """Draw the walker marker at the given position with direction heading.

        Args:
            surface: Target Pygame surface.
            lat: Latitude.
            lon: Longitude.
            heading_deg: Optional heading angle in degrees (0 = North).
        """
        px, py = self.latlon_to_pixel(lat, lon)
        surface.set_clip(self.viewport_rect)

        # Outer pulse / glow ring
        pygame.draw.circle(surface, (255, 255, 255, 120), (px, py), 9)
        # Inner marker circle
        pygame.draw.circle(surface, COLOR_WALKER, (px, py), 7)
        pygame.draw.circle(surface, COLOR_WALKER_OUTLINE, (px, py), 7, 2)

        # Heading indicator needle
        if heading_deg is not None:
            rad = math.radians(heading_deg - 90)  # Screen coords: 0 deg North -> -90 deg
            tip_x = int(px + 12 * math.cos(rad))
            tip_y = int(py + 12 * math.sin(rad))
            pygame.draw.line(surface, (20, 20, 20), (px, py), (tip_x, tip_y), 3)

        surface.set_clip(None)

    def draw_start_end_markers(
        self,
        surface: pygame.Surface,
        start_latlon: Optional[tuple[float, float]],
        end_latlon: Optional[tuple[float, float]],
    ) -> None:
        """Draw Start (Green) and End (Red) pins on the map."""
        surface.set_clip(self.viewport_rect)
        self._ensure_fonts()

        if start_latlon:
            sx, sy = self.latlon_to_pixel(*start_latlon)
            pygame.draw.circle(surface, COLOR_START_NODE, (sx, sy), 8)
            pygame.draw.circle(surface, (255, 255, 255), (sx, sy), 8, 2)
            if self.font_bold:
                lbl = self.font_bold.render("S", True, (255, 255, 255))
                surface.blit(lbl, (sx - 4, sy - 9))

        if end_latlon:
            ex, ey = self.latlon_to_pixel(*end_latlon)
            pygame.draw.circle(surface, COLOR_END_NODE, (ex, ey), 8)
            pygame.draw.circle(surface, (255, 255, 255), (ex, ey), 8, 2)
            if self.font_bold:
                lbl = self.font_bold.render("E", True, (255, 255, 255))
                surface.blit(lbl, (ex - 4, ey - 9))

        surface.set_clip(None)

    def draw_footer_attribution(self, surface: pygame.Surface) -> None:
        """Draw required OpenStreetMap copyright attribution at the bottom of the map."""
        self._ensure_fonts()
        if self.font_small:
            text = "(c) OpenStreetMap contributors | SafeRoute Simulation"
            rendered = self.font_small.render(text, True, COLOR_ATTRIBUTION)
            x = self.viewport_rect.x + 10
            y = self.viewport_rect.bottom - 22
            surface.blit(rendered, (x, y))
