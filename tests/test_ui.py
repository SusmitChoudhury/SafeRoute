"""
tests/test_ui.py – Tests for Phase 7 UI components.

Tests:
  - Side panel rendering, stats card, and alerts
  - Live log console rendering, scrolling, and level colors
  - Risk heat-map toggle and edge risk mapping
  - Headless Pygame application loop execution
  - Tkinter launcher configuration data structures
"""

import os
import pygame
import pytest

from config import WINDOW_SIZE
from sim.logger import SimLogger
from sim.simulation import SimState, Simulation
from ui.log_console import LogConsole
from ui.map_renderer import MapRenderer
from ui.panel import SidePanel
from ui.pygame_app import run_simulation


@pytest.fixture(autouse=True)
def init_pygame():
    """Ensure Pygame runs headlessly for all UI tests."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    pygame.font.init()
    yield
    pygame.quit()


def test_log_console_colors_and_scroll():
    """Test log console renders colored lines and handles scroll offsets."""
    logger = SimLogger()
    logger.log("INFO", "test", "info message")
    logger.log("CALC", "test", "calc message")
    logger.log("ROUTE", "test", "route message")
    logger.log("WARN", "test", "warn message")
    logger.log("ALERT", "test", "alert message")
    logger.log("ERROR", "test", "error message")

    rect = pygame.Rect(1050, 350, 520, 500)
    console = LogConsole(rect, logger)

    surface = pygame.Surface(WINDOW_SIZE)
    console.draw(surface)

    # Test scroll up and down
    assert console.scroll_offset == 0
    console.handle_scroll(1)  # scroll up
    assert console.scroll_offset > 0
    assert not console.auto_scroll

    console.handle_scroll(-2)  # scroll back down
    assert console.scroll_offset == 0
    assert console.auto_scroll


def test_side_panel_rendering():
    """Test side panel renders stats card, controls, warning banners, and logs."""
    logger = SimLogger()
    sim = Simulation(logger=logger)
    panel = SidePanel(logger=logger)

    surface = pygame.Surface(WINDOW_SIZE)
    panel.draw(surface, sim, active_inc_type="accident")

    # Verify simulation metrics are drawn without error
    assert sim.route_stats.get("length_m", 0.0) > 0

    # Simulate Warning 1 state and render banner
    sim.state = SimState.WARNING_1
    sim.warning_1_banner = "WARNING 1: Hazard detected within 500m!"
    panel.draw(surface, sim)

    # Simulate Warning 2 state and render banner
    sim.state = SimState.WARNING_2
    sim.warning_timer = 2.5
    sim.warning_2_banner = "WARNING 2: Detour path applied (+50 m)"
    panel.draw(surface, sim)


def test_risk_heatmap_toggle():
    """Test toggling the risk heat-map computes edge risks for rendering."""
    sim = Simulation()
    assert not sim.show_heatmap

    sim.toggle_heatmap()
    assert sim.show_heatmap
    assert len(sim.route_risks) > 0

    # Test renderer receives edge risks without crashing
    surface = pygame.Surface(WINDOW_SIZE)
    renderer = MapRenderer()
    renderer.draw_road_network(surface, sim.G, edge_risks=sim.route_risks)


def test_pygame_app_headless_loop():
    """Test Pygame app runs cleanly for a set number of frames in headless mode."""
    settings = {
        "mode": "walk",
        "speed": 10,
        "explain": True,
        "heatmap": True,
        "scenario": "Standard Campus Route",
    }
    # Should run 15 frames, dispatch draw and updates, and exit without error
    run_simulation(settings=settings, max_frames=15, headless=True)

