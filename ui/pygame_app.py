"""
ui/pygame_app.py – Pygame main application loop and event coordinator.

Connects:
  - MapRenderer (left 65%): OSM basemap, road network, route lines, danger zones, walker
  - SidePanel (right 35%): Stats card, live colored log console, alerts, controls guide
  - Simulation state machine: detect-and-reroute, multi-modal speed, look-ahead binary search
  - AudioManager: synthesized Warning 1 and Warning 2 beeps
"""

import os
import sys
from typing import Optional
import pygame

from config import (
    DEFAULT_START_LATLON,
    DEFAULT_END_LATLON,
    INCIDENT_TYPES,
    WINDOW_SIZE,
)
from sim.logger import SimLogger
from sim.simulation import SimState, Simulation
from ui.map_renderer import MapRenderer
from ui.panel import SidePanel


def run_simulation(
    settings: Optional[dict] = None,
    max_frames: Optional[int] = None,
    headless: bool = False,
) -> None:
    """Run the 60 FPS Pygame simulation loop.

    Args:
        settings: Configuration dictionary from Tkinter launcher, containing:
                  'mode' (walk/bike/car), 'speed' (1/10/50), 'explain' (bool),
                  'heatmap' (bool), 'scenario' (str).
        max_frames: Optional maximum number of frames to run (used for automated acceptance tests).
        headless: If True, uses the dummy video driver for offscreen testing.
    """
    if settings is None:
        settings = {
            "mode": "walk",
            "speed": 10,
            "explain": False,
            "heatmap": False,
            "scenario": "Standard Campus Route",
        }

    if headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"

    pygame.init()
    pygame.font.init()

    # Create window surface
    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption("SafeRoute – Real-time Hazard-Aware Route Simulator (CSM216)")

    # Components
    logger = SimLogger()
    sim = Simulation(
        mode=settings.get("mode", "walk"),
        speed_scale=settings.get("speed", 10),
        logger=logger,
    )
    sim.explain_mode = settings.get("explain", False)
    sim.show_heatmap = settings.get("heatmap", False)

    renderer = MapRenderer()
    panel = SidePanel(logger=logger)

    clock = pygame.time.Clock()
    active_inc_type = "accident"
    running = True
    frame_count = 0

    # Handle initial scenario
    if settings.get("scenario") == "Scripted Demo (Seed 42)":
        from sim.scripted_demo import setup_scripted_demo
        setup_scripted_demo(sim)

    while running:
        # 60 FPS clock tick
        real_dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos

                # Mouse Wheel on Side Panel Console
                if event.button == 4:  # Scroll Up
                    if panel.log_console and panel.console_rect.collidepoint(mx, my):
                        panel.log_console.handle_scroll(-1)
                elif event.button == 5:  # Scroll Down
                    if panel.log_console and panel.console_rect.collidepoint(mx, my):
                        panel.log_console.handle_scroll(1)

                # Left Click on Map -> Drop incident of active type
                elif event.button == 1:
                    if renderer.viewport_rect.collidepoint(mx, my):
                        lat, lon = renderer.pixel_to_latlon(mx, my)
                        sim.drop_incident(lat, lon, inc_type=active_inc_type)

                # Right Click on Map -> Remove nearby incident
                elif event.button == 3:
                    if renderer.viewport_rect.collidepoint(mx, my):
                        lat, lon = renderer.pixel_to_latlon(mx, my)
                        sim.remove_incident_near(lat, lon, max_dist_m=120.0)

            elif event.type == pygame.KEYDOWN:
                # Space: Start / Pause
                if event.key == pygame.K_SPACE:
                    sim.start_or_pause()

                # 1 / 2 / 3: Travel Mode
                elif event.key == pygame.K_1:
                    sim.set_mode("walk")
                elif event.key == pygame.K_2:
                    sim.set_mode("bike")
                elif event.key == pygame.K_3:
                    sim.set_mode("car")

                # Q W E R T: Select Incident Type
                elif event.key == pygame.K_q:
                    active_inc_type = "accident"
                    sim.logger.log("INFO", "input", "selected incident type: ACCIDENT", sim.sim_time)
                elif event.key == pygame.K_w:
                    active_inc_type = "flooding"
                    sim.logger.log("INFO", "input", "selected incident type: FLOODING", sim.sim_time)
                elif event.key == pygame.K_e:
                    active_inc_type = "unsafe_area"
                    sim.logger.log("INFO", "input", "selected incident type: UNSAFE_AREA", sim.sim_time)
                elif event.key == pygame.K_r:
                    active_inc_type = "construction"
                    sim.logger.log("INFO", "input", "selected incident type: CONSTRUCTION", sim.sim_time)
                elif event.key == pygame.K_t:
                    active_inc_type = "road_damage"
                    sim.logger.log("INFO", "input", "selected incident type: ROAD_DAMAGE", sim.sim_time)

                # + / -: Simulation speed scale
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    sim.cycle_speed(forward=True)
                elif event.key in (pygame.K_MINUS, pygame.K_UNDERSCORE, pygame.K_KP_MINUS):
                    sim.cycle_speed(forward=False)

                # L: Explain mode toggle
                elif event.key == pygame.K_l:
                    sim.toggle_explain()

                # H: Risk Heat-map toggle
                elif event.key == pygame.K_h:
                    sim.toggle_heatmap()

                # F5: Scripted Demo trigger
                elif event.key == pygame.K_F5:
                    from sim.scripted_demo import setup_scripted_demo
                    setup_scripted_demo(sim)

                # Esc: Reset simulation
                elif event.key == pygame.K_ESCAPE:
                    sim.reset()

        # Update simulation logic
        sim.update(real_dt)

        # Draw Frame
        # 1. Clear background & basemap
        renderer.draw_basemap(screen)

        # 2. Road Network (with risk heat-map if toggled)
        edge_risks = sim.route_risks if sim.show_heatmap else None
        renderer.draw_road_network(screen, sim.G, edge_risks=edge_risks)

        # 3. Old route (faded red) if rerouted
        if sim.previous_route:
            renderer.draw_route(screen, sim.G, sim.previous_route, is_active=False)

        # 4. Current active route (blue)
        if sim.current_route:
            renderer.draw_route(screen, sim.G, sim.current_route, is_active=True)

        # 5. Active Danger Zones
        active_incidents = sim.incident_store.get_active_incidents()
        for inc in active_incidents:
            renderer.draw_incident(screen, inc)

        # 6. Start (Green) & End (Red) Pin Markers
        renderer.draw_start_end_markers(screen, sim.start_latlon, sim.end_latlon)

        # 7. Animated Walker
        if sim.walker:
            renderer.draw_walker(
                screen,
                sim.walker.lat,
                sim.walker.lon,
                heading_deg=sim.walker.heading_deg,
            )

        # 8. Basemap Copyright Attribution
        renderer.draw_footer_attribution(screen)

        # 9. Right-hand Side Panel & Live Colored Log
        panel.draw(screen, sim, active_inc_type=active_inc_type)

        # Refresh display
        pygame.display.flip()

        frame_count += 1
        if max_frames is not None and frame_count >= max_frames:
            break

    pygame.quit()


if __name__ == "__main__":
    run_simulation()
