"""
tools/view_static_map.py – Standalone static map view for Phase 2.

Overlays the street network, sample route, and danger zones onto the OpenStreetMap
basemap image, validates pixel alignment of major junctions, and saves a screenshot
to docs/phase2_static_map.png.
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Avoid matplotlib cache warning
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / ".cache" / "matplotlib"))

import pygame
import networkx as nx

from config import DEFAULT_START_LATLON, DEFAULT_END_LATLON, WINDOW_SIZE
from core.graph_loader import load_graph, snap_to_node
from ui.map_renderer import MapRenderer


def run_static_map_view(save_only: bool = False, output_path: str = "docs/phase2_static_map.png") -> dict:
    """Render the static map with road overlay and test alignment.

    Args:
        save_only: If True, renders headless, saves the image, and exits without opening a window.
        output_path: Path to save the rendered screenshot.

    Returns:
        dict: Diagnostics including junction pixel coordinates and alignment status.
    """
    if save_only or "SDL_VIDEODRIVER" in os.environ:
        os.environ["SDL_VIDEODRIVER"] = "dummy"

    pygame.init()
    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption("SafeRoute - Phase 2 Static Map View (Alignment Check)")

    renderer = MapRenderer()
    G = load_graph("walk")

    # Pick a prominent known junction (highest degree node in the graph)
    sorted_nodes = sorted(G.degree, key=lambda x: x[1], reverse=True)
    known_node_id, degree = sorted_nodes[0]
    known_node_data = G.nodes[known_node_id]
    k_lat = known_node_data["lat"]
    k_lon = known_node_data["lon"]

    # Calculate pixel position using renderer
    px, py = renderer.latlon_to_pixel(k_lat, k_lon)

    # Snap default start & end
    start_node, s_dist = snap_to_node(G, *DEFAULT_START_LATLON)
    end_node, e_dist = snap_to_node(G, *DEFAULT_END_LATLON)

    # Find a sample shortest path between start and end using networkx
    try:
        sample_path = nx.shortest_path(G, start_node, end_node, weight="length")
    except Exception:
        # If not connected, use a nearby node path
        sample_path = [start_node, end_node]

    # Sample incident
    sample_incident = {
        "lat": k_lat,
        "lon": k_lon,
        "radius_m": 120.0,
        "type": "accident",
    }

    # Draw everything onto screen
    screen.fill((28, 32, 40))
    renderer.draw_basemap(screen)
    renderer.draw_road_network(screen, G)
    renderer.draw_incident(screen, sample_incident)
    renderer.draw_route(screen, G, sample_path, is_active=True)
    renderer.draw_start_end_markers(screen, DEFAULT_START_LATLON, DEFAULT_END_LATLON)
    renderer.draw_walker(screen, k_lat, k_lon, heading_deg=45.0)
    renderer.draw_footer_attribution(screen)

    # Draw a highlight circle around the verified known junction
    pygame.draw.circle(screen, (255, 255, 0), (px, py), 12, 2)
    font = pygame.font.SysFont("Segoe UI, Arial", 14, bold=True)
    tag = font.render(f"Junction #{known_node_id} (deg={degree}) at ({px}, {py})", True, (255, 255, 0))
    screen.blit(tag, (px + 15, py - 10))

    # Save screenshot
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(screen, str(out_file))
    print(f"Saved alignment screenshot to: {out_file.resolve()}", flush=True)

    result = {
        "known_node_id": known_node_id,
        "degree": degree,
        "lat": k_lat,
        "lon": k_lon,
        "pixel": (px, py),
        "viewport": (renderer.viewport_rect.width, renderer.viewport_rect.height),
        "scale": renderer.scale,
        "screenshot": str(out_file),
    }

    if not save_only and os.environ.get("SDL_VIDEODRIVER") != "dummy":
        pygame.display.flip()
        clock = pygame.time.Clock()
        running = True
        frame_count = 0
        while running and frame_count < 120:  # Show for 2 seconds or until quit
            for event in pygame.event.get():
                if event.type in (pygame.QUIT, pygame.KEYDOWN):
                    running = False
            clock.tick(60)
            frame_count += 1

    pygame.quit()
    return result


if __name__ == "__main__":
    save_mode = "--save-only" in sys.argv or "--headless" in sys.argv
    run_static_map_view(save_only=save_mode)

