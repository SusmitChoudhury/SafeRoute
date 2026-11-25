"""
tools/render_preview.py – Render high-resolution preview of the software UI to an image file.
"""

import os
import sys
from pathlib import Path
import pygame

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Run headless
os.environ["SDL_VIDEODRIVER"] = "dummy"
pygame.init()
pygame.font.init()

from config import WINDOW_SIZE
from sim.simulation import Simulation, SimState
from ui.map_renderer import MapRenderer
from ui.panel import SidePanel

def generate_preview():
    sim = Simulation()
    renderer = MapRenderer()
    panel = SidePanel(logger=sim.logger)

    surface = pygame.Surface(WINDOW_SIZE)
    surface.fill((20, 24, 36))

    # 1. Basemap
    renderer.draw_basemap(surface)

    # 2. Road network
    renderer.draw_road_network(surface, sim.G, edge_risks=sim.route_risks)

    # 3. Incidents
    incidents = sim.incident_store.get_active_incidents()
    for inc in incidents:
        renderer.draw_incident(surface, inc)

    # 4. Route
    renderer.draw_route(surface, sim.current_route, sim.G)

    # 5. Start and End pins
    renderer.draw_start_end_markers(surface, sim.start_latlon, sim.end_latlon)

    # 6. Walker
    if sim.walker:
        renderer.draw_walker(surface, sim.walker.lat, sim.walker.lon, heading_deg=sim.walker.heading_deg)

    # 7. Side panel (stats card, multi-modal comparison, live terminal)
    panel.draw(surface, sim, active_inc_type="accident")

    out_path = Path("docs") / "software_preview.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(out_path))
    print(f"Saved preview image to {out_path} ({out_path.stat().st_size} bytes)")

if __name__ == "__main__":
    generate_preview()
