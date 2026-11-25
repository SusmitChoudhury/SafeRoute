"""
ui/panel.py – Side panel containing the algorithm stats card, controls, and live log console.

Components:
  1. Route Stats Card (Distance, ETAs for Walk/Bike/Car, active mode, sim speed)
  2. Warning Alert Banners (Warning 1 & Warning 2 banners)
  3. Interactive Control Hints (keys, mouse modes)
  4. Live Log Console
  5. Data quality disclaimer footer (SIMULATED data, seed=42)
"""

from typing import Optional
import pygame

from config import WINDOW_SIZE, MAP_PANEL_WIDTH_FRAC
from sim.logger import SimLogger
from sim.simulation import SimState, Simulation
from ui.log_console import LogConsole

# Theme colors – Premium Modern Slate & Glassmorphism
COLOR_PANEL_BG = (15, 23, 42)        # Deep navy slate (#0f172a)
COLOR_CARD_BG = (30, 41, 59)         # Elevated card slate (#1e293b)
COLOR_BORDER = (51, 65, 85)          # Muted border (#334155)
COLOR_TEXT_MAIN = (248, 250, 252)    # Pure slate white (#f8fafc)
COLOR_TEXT_MUTED = (148, 163, 184)   # Soft silver (#94a3b8)
COLOR_ACCENT = (56, 189, 248)        # Electric sky blue (#38bdf8)
COLOR_WARN_1 = (245, 158, 11)        # Radiant amber (#f59e0b)
COLOR_WARN_2 = (16, 185, 129)        # Emerald detour green (#10b981)


class SidePanel:
    """Renders the comprehensive dashboard on the right 35% of the window."""

    def __init__(self, rect: Optional[pygame.Rect] = None, logger: Optional[SimLogger] = None):
        if rect is None:
            map_w = int(WINDOW_SIZE[0] * MAP_PANEL_WIDTH_FRAC)
            panel_w = WINDOW_SIZE[0] - map_w
            self.rect = pygame.Rect(map_w, 0, panel_w, WINDOW_SIZE[1])
        else:
            self.rect = rect

        self.logger = logger
        # Setup log console in bottom half of side panel
        console_top = self.rect.y + 365
        console_height = self.rect.height - 365 - 32  # Leave room for footer
        self.console_rect = pygame.Rect(
            self.rect.x + 12,
            console_top,
            self.rect.width - 24,
            console_height,
        )
        self.log_console = LogConsole(self.console_rect, logger, line_height=25) if logger else None

        self.font_title: Optional[pygame.font.Font] = None
        self.font_main: Optional[pygame.font.Font] = None
        self.font_bold: Optional[pygame.font.Font] = None
        self.font_small: Optional[pygame.font.Font] = None
        self._init_fonts()

    def _init_fonts(self) -> None:
        if not pygame.font.get_init():
            pygame.font.init()
        # Increased font sizes for high-DPI and clear screen recordings
        self.font_title = pygame.font.SysFont("Segoe UI, -apple-system, Arial", 22, bold=True)
        self.font_main = pygame.font.SysFont("Segoe UI, -apple-system, Arial", 15)
        self.font_bold = pygame.font.SysFont("Segoe UI, -apple-system, Arial", 15, bold=True)
        self.font_small = pygame.font.SysFont("Segoe UI, -apple-system, Arial", 13)

    def draw(self, surface: pygame.Surface, sim: Simulation, active_inc_type: str = "accident") -> None:
        """Draw the entire side panel."""
        surface.set_clip(self.rect)
        pygame.draw.rect(surface, COLOR_PANEL_BG, self.rect)
        pygame.draw.line(surface, COLOR_BORDER, (self.rect.x, 0), (self.rect.x, self.rect.height), 2)

        x = self.rect.x + 14
        y = self.rect.y + 12

        # 1. Header
        if self.font_title:
            title_surf = self.font_title.render("SafeRoute Dashboard", True, COLOR_TEXT_MAIN)
            surface.blit(title_surf, (x, y))
        y += 30

        # 2. Stats Card Box
        card_rect = pygame.Rect(x, y, self.rect.width - 28, 140)
        pygame.draw.rect(surface, COLOR_CARD_BG, card_rect, border_radius=6)
        pygame.draw.rect(surface, COLOR_BORDER, card_rect, 1, border_radius=6)

        cy = y + 8
        if self.font_bold and self.font_main:
            # Active mode & status
            mode_lbl = self.font_bold.render(f"Mode: {sim.mode.upper()}", True, COLOR_ACCENT)
            surface.blit(mode_lbl, (x + 10, cy))

            status_str = f"Status: {sim.state.name}"
            if sim.is_paused:
                status_str += " (PAUSED)"
            status_lbl = self.font_main.render(status_str, True, COLOR_TEXT_MAIN)
            surface.blit(status_lbl, (x + 140, cy))

            speed_lbl = self.font_main.render(f"Speed: x{sim.time_scale}", True, COLOR_TEXT_MUTED)
            surface.blit(speed_lbl, (x + card_rect.width - 90, cy))
            cy += 24

            # Route distance & walker progress
            route_m = sim.route_stats.get("length_m", 0.0)
            walked_m = sim.walker.distance_travelled if sim.walker else 0.0
            dist_str = f"Route: {route_m:.0f} m  |  Traveled: {walked_m:.0f} m"
            surface.blit(self.font_main.render(dist_str, True, COLOR_TEXT_MAIN), (x + 10, cy))
            cy += 24

            # Multi-modal travel time comparison
            surface.blit(self.font_bold.render("Mode Comparison (ETA):", True, COLOR_TEXT_MUTED), (x + 10, cy))
            cy += 20
            walk_eta = sim.all_mode_etas.get("walk", {}).get("eta_minutes", 0.0)
            bike_eta = sim.all_mode_etas.get("bike", {}).get("eta_minutes", 0.0)
            car_eta = sim.all_mode_etas.get("car", {}).get("eta_minutes", 0.0)
            modes_str = f"Walk: {walk_eta:.1f}m  |  Bike: {bike_eta:.1f}m  |  Car: {car_eta:.1f}m"
            surface.blit(self.font_main.render(modes_str, True, (46, 204, 113)), (x + 10, cy))
            cy += 20

            # Metrics
            metrics_str = f"Reroutes: {sim.reroute_count}  |  Avoided: {sim.incidents_avoided}  |  Warnings: {sim.warnings_count}"
            surface.blit(self.font_small.render(metrics_str, True, COLOR_TEXT_MUTED), (x + 10, cy))

        y += 150

        # 3. Warning Alert Banners
        if sim.state in (SimState.WARNING_1, SimState.REROUTING) or (sim.warning_1_banner and sim.state == SimState.WARNING_1):
            banner_rect = pygame.Rect(x, y, self.rect.width - 28, 36)
            pygame.draw.rect(surface, (180, 40, 40), banner_rect, border_radius=4)
            if self.font_bold:
                txt = self.font_bold.render(sim.warning_1_banner or "WARNING 1: Danger ahead - Recalculating!", True, (255, 255, 255))
                surface.blit(txt, (x + 8, y + 8))
            y += 42
        elif sim.state == SimState.WARNING_2 or (sim.warning_timer > 0 and sim.warning_2_banner):
            banner_rect = pygame.Rect(x, y, self.rect.width - 28, 36)
            pygame.draw.rect(surface, (39, 140, 75), banner_rect, border_radius=4)
            if self.font_bold:
                txt = self.font_bold.render(sim.warning_2_banner or "WARNING 2: Detour path applied!", True, (255, 255, 255))
                surface.blit(txt, (x + 8, y + 8))
            y += 42
        else:
            y += 6

        # 4. Controls Guide
        ctrl_rect = pygame.Rect(x, y, self.rect.width - 28, 95)
        pygame.draw.rect(surface, (28, 33, 42), ctrl_rect, border_radius=4)
        if self.font_small and self.font_bold:
            cy = y + 6
            surface.blit(self.font_bold.render(f"Incident Type: {active_inc_type.upper()} [Keys Q,W,E,R,T]", True, (241, 196, 15)), (x + 8, cy))
            cy += 18
            surface.blit(self.font_small.render("Left Click: Drop incident  |  Right Click: Remove", True, COLOR_TEXT_MAIN), (x + 8, cy))
            cy += 16
            surface.blit(self.font_small.render("Space: Start/Pause  |  1/2/3: Mode  |  F5: Scripted Demo", True, COLOR_TEXT_MAIN), (x + 8, cy))
            cy += 16
            surface.blit(self.font_small.render("L: Explain Mode  |  H: Heat-map  |  +/-: Speed  |  Esc: Reset", True, COLOR_TEXT_MAIN), (x + 8, cy))
            cy += 16
            explain_status = f"Explain Mode: {'ON' if sim.explain_mode else 'OFF'}  |  Heat-map: {'ON' if sim.show_heatmap else 'OFF'}"
            surface.blit(self.font_small.render(explain_status, True, COLOR_ACCENT), (x + 8, cy))

        # 5. Live Log Console
        if self.log_console:
            self.log_console.draw(surface)

        # 6. Disclaimer Footer
        if self.font_small:
            footer_text = "WARN: incident data is SIMULATED (seed=42) | CSM216 Project"
            foot_surf = self.font_small.render(footer_text, True, (230, 126, 34))
            surface.blit(foot_surf, (x, self.rect.bottom - 22))

        surface.set_clip(None)
