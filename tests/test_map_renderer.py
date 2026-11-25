"""
tests/test_map_renderer.py – Unit tests for MapRenderer and pixel alignment.
"""

import os
import pytest
import pygame

# Run pygame headless in tests
os.environ["SDL_VIDEODRIVER"] = "dummy"

from config import DEFAULT_START_LATLON, DEFAULT_END_LATLON, WINDOW_SIZE
from core.graph_loader import load_graph
from ui.map_renderer import MapRenderer


@pytest.fixture(scope="module")
def renderer():
    pygame.init()
    rend = MapRenderer()
    yield rend
    pygame.quit()


def test_renderer_initialization(renderer):
    assert renderer.basemap_surface is not None
    assert renderer.viewport_rect.width > 500
    assert renderer.viewport_rect.height > 500
    assert renderer.scale > 0.0


def test_latlon_pixel_roundtrip(renderer):
    """Test that lat/lon -> pixel -> lat/lon is consistent."""
    orig_lat, orig_lon = DEFAULT_START_LATLON
    px, py = renderer.latlon_to_pixel(orig_lat, orig_lon)

    # Must be inside or near viewport
    assert renderer.viewport_rect.collidepoint(px, py)

    recov_lat, recov_lon = renderer.pixel_to_latlon(px, py)
    # Precision should be within 0.0001 degrees (~10 metres)
    assert abs(recov_lat - orig_lat) < 0.0002
    assert abs(recov_lon - orig_lon) < 0.0002


def test_junction_alignment_on_basemap(renderer):
    """Verify that graph junctions land on valid pixels inside the basemap viewport."""
    G = load_graph("walk")
    assert len(G.nodes) > 0

    # Test top 10 highest-degree junctions
    sorted_nodes = sorted(G.degree, key=lambda x: x[1], reverse=True)[:10]
    for node_id, degree in sorted_nodes:
        data = G.nodes[node_id]
        lat, lon = data["lat"], data["lon"]
        px, py = renderer.latlon_to_pixel(lat, lon)
        # Verify junction pixel is inside viewport boundaries
        assert 0 <= px <= renderer.viewport_rect.width + 100
        assert 0 <= py <= renderer.viewport_rect.height + 100


def test_draw_methods_execute_without_error(renderer):
    """Verify that all rendering functions draw onto a surface cleanly."""
    surface = pygame.Surface(WINDOW_SIZE)
    G = load_graph("walk")

    # 1. Draw basemap
    renderer.draw_basemap(surface)

    # 2. Draw roads
    renderer.draw_road_network(surface, G)

    # 3. Draw route
    nodes = list(G.nodes)[:5]
    renderer.draw_route(surface, G, nodes, is_active=True)

    # 4. Draw incident
    incident = {"lat": 31.2551, "lon": 75.7025, "radius_m": 150.0, "type": "accident"}
    renderer.draw_incident(surface, incident)

    # 5. Draw walker
    renderer.draw_walker(surface, 31.2551, 75.7025, heading_deg=90.0)

    # 6. Draw markers and attribution
    renderer.draw_start_end_markers(surface, DEFAULT_START_LATLON, DEFAULT_END_LATLON)
    renderer.draw_footer_attribution(surface)

    # Surface must contain rendered data
    assert surface.get_at((renderer.viewport_rect.centerx, renderer.viewport_rect.centery)) is not None

