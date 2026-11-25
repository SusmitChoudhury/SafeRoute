"""
tools/prepare_data.py – One-off download of OSM graphs and basemap.

Usage:
    python tools/prepare_data.py --center 31.2551,75.7025 --dist 1500

Downloads walk, bike, and drive street networks for the specified center
and radius, projects them to UTM, preserves WGS84 lat/lon on nodes, and
saves them to data/cache/. Also fetches the OpenStreetMap basemap via
tile stitching (using contextily/mercantile) and saves basemap.png and
basemap_meta.json.

After running this once, the entire SafeRoute application runs offline.
"""

import argparse
import io
import json
import math
import os
import sys
import time
from pathlib import Path

# Add project root to path so we can import config
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Avoid matplotlib cache warning
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / ".cache" / "matplotlib"))

from PIL import Image
import mercantile
import networkx as nx
import osmnx as ox
import pyproj
import requests

from config import CENTER_LATLON, RADIUS_M

CACHE_DIR = PROJECT_ROOT / "data" / "cache"
HTTP_HEADERS = {
    "User-Agent": "SafeRoute-Academic-Project/1.0 (Lovely Professional University CSM216 Project; student demo)"
}


def download_osm_xml(lat: float, lon: float, dist_m: float) -> Path:
    """Download raw OSM XML from OpenStreetMap API.

    Args:
        lat: Center latitude.
        lon: Center longitude.
        dist_m: Radius in metres.

    Returns:
        Path to the saved XML file.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    xml_path = CACHE_DIR / "osm_raw.osm"

    # Add 150m buffer so boundary intersections are fully represented
    delta_lat = (dist_m + 150) / 111000.0
    delta_lon = (dist_m + 150) / (111000.0 * math.cos(math.radians(lat)))

    min_lat = lat - delta_lat
    max_lat = lat + delta_lat
    min_lon = lon - delta_lon
    max_lon = lon + delta_lon

    bbox_str = f"{min_lon:.5f},{min_lat:.5f},{max_lon:.5f},{max_lat:.5f}"
    url = f"https://api.openstreetmap.org/api/0.6/map?bbox={bbox_str}"
    print(f"Downloading OSM data from official OSM API: {url}", flush=True)

    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()

    xml_path.write_bytes(resp.content)
    print(f"Saved OSM XML: {xml_path} ({len(resp.content):,} bytes)", flush=True)
    return xml_path


def build_graphs_from_osm(xml_path: Path) -> dict[str, nx.MultiDiGraph]:
    """Parse raw OSM XML into separate MultiDiGraphs for walk, bike, and drive.

    Args:
        xml_path: Path to the raw OSM XML file.

    Returns:
        dict[str, nx.MultiDiGraph]: {'walk': G_walk, 'bike': G_bike, 'drive': G_drive}
    """
    print(f"Parsing {xml_path} with OSMnx...", flush=True)
    # Parse base graph from XML (all ways)
    G_base = ox.graph_from_xml(str(xml_path), simplify=True)
    print(f"Base graph parsed: {len(G_base.nodes):,} nodes, {len(G_base.edges):,} edges", flush=True)

    # Road classes that each mode can use
    walk_disallowed = {"motorway", "motorway_link", "trunk", "trunk_link"}
    bike_disallowed = {"motorway", "motorway_link", "steps"}
    drive_disallowed = {"footway", "steps", "pedestrian", "path", "cycleway", "bridleway", "corridor"}

    graphs = {}
    for mode in ["walk", "bike", "drive"]:
        G_sub = G_base.copy()
        remove_edges = []

        for u, v, k, data in G_sub.edges(keys=True, data=True):
            hw = data.get("highway", "")
            if isinstance(hw, list):
                hw = hw[0] if hw else ""

            if mode == "walk" and hw in walk_disallowed:
                remove_edges.append((u, v, k))
            elif mode == "bike" and hw in bike_disallowed:
                remove_edges.append((u, v, k))
            elif mode == "drive" and hw in drive_disallowed:
                remove_edges.append((u, v, k))

        for edge in remove_edges:
            if G_sub.has_edge(*edge):
                G_sub.remove_edge(*edge)

        # Remove isolated nodes without edges
        isolated = list(nx.isolates(G_sub))
        G_sub.remove_nodes_from(isolated)

        graphs[mode] = G_sub
        print(f"Mode '{mode}': {len(G_sub.nodes):,} nodes, {len(G_sub.edges):,} edges", flush=True)

    return graphs


def project_and_save_graph(G: nx.MultiDiGraph, mode: str) -> Path:
    """Project graph to UTM metres, preserve WGS84 lat/lon, and save to GraphML.

    Args:
        G: Unprojected graph.
        mode: 'walk', 'bike', or 'drive'.

    Returns:
        Path to saved GraphML file.
    """
    # 1. Preserve lat / lon on all nodes before projection converts x/y to metres
    for _, data in G.nodes(data=True):
        data["lat"] = float(data.get("y", 0.0))
        data["lon"] = float(data.get("x", 0.0))

    # 2. Project to UTM coordinate reference system
    G_proj = ox.project_graph(G)

    # 3. Explicitly ensure x, y, lat, lon are typed floats and length is present
    for _, data in G_proj.nodes(data=True):
        data["x"] = float(data["x"])
        data["y"] = float(data["y"])
        data["lat"] = float(data["lat"])
        data["lon"] = float(data["lon"])

    for u, v, k, data in G_proj.edges(keys=True, data=True):
        if "length" in data:
            data["length"] = float(data["length"])
        else:
            # Fallback: Euclidean distance in UTM metres
            ux, uy = G_proj.nodes[u]["x"], G_proj.nodes[u]["y"]
            vx, vy = G_proj.nodes[v]["x"], G_proj.nodes[v]["y"]
            data["length"] = float(math.hypot(vx - ux, vy - uy))

    out_path = CACHE_DIR / f"graph_{mode}.graphml"
    ox.save_graphml(G_proj, filepath=out_path)
    print(f"Saved {mode} graph: {out_path} ({len(G_proj.nodes):,} nodes, {len(G_proj.edges):,} edges)", flush=True)
    return out_path


def download_and_save_basemap(lat: float, lon: float, dist_m: float) -> tuple[Path, Path]:
    """Download OpenStreetMap basemap tiles and save as PNG with extent metadata.

    Args:
        lat: Center latitude.
        lon: Center longitude.
        dist_m: Radius in metres.

    Returns:
        tuple[Path, Path]: (basemap_png_path, basemap_meta_json_path)
    """
    print("Downloading OpenStreetMap basemap tiles...", flush=True)
    # Add 15% margin so road networks fit comfortably within the image
    margin = dist_m * 1.15
    delta_lat = margin / 111000.0
    delta_lon = margin / (111000.0 * math.cos(math.radians(lat)))

    min_lat = lat - delta_lat
    max_lat = lat + delta_lat
    min_lon = lon - delta_lon
    max_lon = lon + delta_lon

    zoom = 15
    tiles = list(mercantile.tiles(min_lon, min_lat, max_lon, max_lat, zoom))
    print(f"Fetching {len(tiles)} tiles at zoom={zoom}...", flush=True)

    xs = [t.x for t in tiles]
    ys = [t.y for t in tiles]
    min_tile_x, max_tile_x = min(xs), max(xs)
    min_tile_y, max_tile_y = min(ys), max(ys)

    width_tiles = max_tile_x - min_tile_x + 1
    height_tiles = max_tile_y - min_tile_y + 1
    stitch = Image.new("RGB", (width_tiles * 256, height_tiles * 256))

    for t in tiles:
        url = f"https://tile.openstreetmap.org/{t.z}/{t.x}/{t.y}.png"
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=HTTP_HEADERS, timeout=8)
                if resp.status_code == 200:
                    tile_img = Image.open(io.BytesIO(resp.content))
                    px = (t.x - min_tile_x) * 256
                    py = (t.y - min_tile_y) * 256
                    stitch.paste(tile_img, (px, py))
                    break
            except Exception:
                time.sleep(0.5)

    png_path = CACHE_DIR / "basemap.png"
    stitch.save(png_path)

    # Compute exact bounding box of stitched tiles in EPSG:3857 (Web Mercator metres)
    # Top-left tile:
    ul_bounds = mercantile.xy_bounds(mercantile.Tile(min_tile_x, min_tile_y, zoom))
    # Bottom-right tile:
    lr_bounds = mercantile.xy_bounds(mercantile.Tile(max_tile_x, max_tile_y, zoom))

    xmin = float(ul_bounds.left)
    xmax = float(lr_bounds.right)
    ymin = float(lr_bounds.bottom)
    ymax = float(ul_bounds.top)

    meta = {
        "extent": [xmin, xmax, ymin, ymax],
        "width": stitch.width,
        "height": stitch.height,
        "crs": "EPSG:3857",
        "center_latlon": [lat, lon],
        "dist_m": dist_m,
    }
    meta_path = CACHE_DIR / "basemap_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"Saved basemap image: {png_path} ({stitch.width}x{stitch.height} px)", flush=True)
    print(f"Saved basemap metadata: {meta_path} (extent: {[xmin, xmax, ymin, ymax]})", flush=True)
    return png_path, meta_path


def main():
    parser = argparse.ArgumentParser(description="Prepare SafeRoute offline map data")
    parser.add_argument(
        "--center",
        type=str,
        default=f"{CENTER_LATLON[0]},{CENTER_LATLON[1]}",
        help="Center latitude,longitude (e.g. 31.2551,75.7025)",
    )
    parser.add_argument(
        "--dist",
        type=float,
        default=float(RADIUS_M),
        help="Search radius in metres (default 1500)",
    )
    args = parser.parse_args()

    lat_str, lon_str = args.center.split(",")
    lat = float(lat_str.strip())
    lon = float(lon_str.strip())
    dist = args.dist

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("=== SafeRoute Data Preparation ===", flush=True)
    print(f"Center: ({lat}, {lon}) | Radius: {dist} m | Cache: {CACHE_DIR}", flush=True)

    # 1. Download raw OSM XML
    xml_path = download_osm_xml(lat, lon, dist)

    # 2. Build and project graphs
    graphs = build_graphs_from_osm(xml_path)
    for mode, G in graphs.items():
        project_and_save_graph(G, mode)

    # 3. Download and save basemap
    download_and_save_basemap(lat, lon, dist)

    print("\n=== Data preparation complete! All offline assets cached. ===", flush=True)


if __name__ == "__main__":
    main()
