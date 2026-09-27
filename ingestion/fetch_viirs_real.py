"""
NASA VIIRS night-time lights for every city.

Requests a 1024 x 1024 image of the city bbox from NASA GIBS (a free WMS
service, no login), converts it to grayscale and scales it to 0-100. When
NASA cannot be reached, a synthetic "bright centre, dark outskirts" surface
is used instead.

Run:
    python -m ingestion.fetch_viirs_real
    python -m ingestion.fetch_viirs_real --city Mumbai
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from ai.ml.features import city_slug
from ingestion.fetch_india_graph import CITY_BBOXES, INDIAN_CITIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("fetch_viirs_real")

DATA_RAW = Path("data/raw")
VIIRS_DIR = DATA_RAW / "viirs"
VIIRS_DIR.mkdir(parents=True, exist_ok=True)

TILE_SIZE = 1024
GIBS_WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
# Tried in order; the second layer is a fallback if the first returns nothing.
VIIRS_LAYERS = ["VIIRS_Black_Marble", "VIIRS_SNPP_DayNightBand_At_Sensor_Radiance"]


def _wms_url(layer: str, bbox: dict) -> str:
    # WMS 1.3.0 with EPSG:4326 expects the box as south,west,north,east.
    return (
        f"{GIBS_WMS}?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0"
        f"&LAYERS={layer}&CRS=EPSG:4326&FORMAT=image/png"
        f"&WIDTH={TILE_SIZE}&HEIGHT={TILE_SIZE}"
        f"&BBOX={bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"
    )


def _download_tile(bbox: dict, png_path: Path) -> np.ndarray | None:
    """First usable VIIRS image for the bbox as a grayscale array, else None."""
    for layer in VIIRS_LAYERS:
        try:
            response = requests.get(_wms_url(layer, bbox), timeout=30)
            if response.status_code == 200 and len(response.content) > 1000:
                image = Image.open(io.BytesIO(response.content)).convert("L")
                image.save(png_path)   # kept for visual inspection
                return np.array(image, dtype=np.float32)
        except Exception as exc:
            log.warning("  %s request failed: %s", layer, exc)
    return None


def fetch_viirs_tile(city_name: str, bbox: dict, force: bool = False) -> np.ndarray | None:
    """Night-light array (1024 x 1024, values 0-100) for one city, cached as .npy."""
    npy_path = VIIRS_DIR / f"{city_slug(city_name)}.npy"
    png_path = VIIRS_DIR / f"{city_slug(city_name)}.png"

    if npy_path.exists() and not force:
        log.info("  %s: VIIRS tile already cached", city_name)
        return np.load(npy_path)

    log.info("  Fetching VIIRS for %s ...", city_name)
    tile = _download_tile(bbox, png_path)
    if tile is None:
        log.warning("  %s: NASA service unavailable, using the radial proxy", city_name)
        tile = _proxy_viirs(city_name, bbox)

    if tile.max() > 0:
        tile = tile / tile.max() * 100
    tile = tile.astype(np.float32)

    np.save(npy_path, tile)
    log.info("  %s: mean %.1f, max %.1f -> %s", city_name, tile.mean(), tile.max(), npy_path.name)
    return tile


def _proxy_viirs(city_name: str, bbox: dict) -> np.ndarray:
    """Synthetic brightness: 80 at the centre fading to 0 at 1.5x the half-height, plus noise."""
    h = w = TILE_SIZE
    centre_lat = (bbox["north"] + bbox["south"]) / 2
    centre_lon = (bbox["east"] + bbox["west"]) / 2
    max_dist = max(bbox["north"] - centre_lat, centre_lat - bbox["south"])

    lats = bbox["north"] - (np.arange(h) / h) * (bbox["north"] - bbox["south"])
    lons = bbox["west"] + (np.arange(w) / w) * (bbox["east"] - bbox["west"])
    dist = np.sqrt((lats[:, None] - centre_lat) ** 2 + (lons[None, :] - centre_lon) ** 2)

    brightness = np.maximum(0, 1 - dist / (max_dist * 1.5))
    noise = np.random.uniform(0, 10, size=(h, w))
    return (brightness * 80 + noise).astype(np.float32)


def pixel_index(lat: float, lon: float, bbox: dict, shape: tuple[int, int]) -> tuple[int, int]:
    """Row and column of the tile pixel covering (lat, lon), clamped to the tile."""
    h, w = shape
    row = int((bbox["north"] - lat) / (bbox["north"] - bbox["south"]) * h)
    col = int((lon - bbox["west"]) / (bbox["east"] - bbox["west"]) * w)
    return max(0, min(row, h - 1)), max(0, min(col, w - 1))


def assign_viirs_to_graph(G, city_name: str, viirs_arr: np.ndarray, bbox: dict) -> None:
    """Sets luminosity_score on every edge from the pixel under its midpoint."""
    if bbox["north"] - bbox["south"] <= 0 or bbox["east"] - bbox["west"] <= 0:
        log.error("Invalid bbox for %s", city_name)
        return

    assigned = 0
    for u, v, data in G.edges(data=True):
        try:
            mid_lat = (float(G.nodes[u]["y"]) + float(G.nodes[v]["y"])) / 2
            mid_lon = (float(G.nodes[u]["x"]) + float(G.nodes[v]["x"])) / 2
        except (KeyError, ValueError):
            continue
        row, col = pixel_index(mid_lat, mid_lon, bbox, viirs_arr.shape)
        data["luminosity_score"] = round(float(viirs_arr[row, col]), 2)
        assigned += 1

    log.info("  VIIRS luminosity set on %s edges in %s", f"{assigned:,}", city_name)


def fetch_all_cities_viirs(cities=None, force: bool = False, delay: float = 2.0) -> dict:
    """Fetches every city's tile and writes a summary JSON."""
    results = {}
    cities = cities or INDIAN_CITIES
    for i, city in enumerate(cities):
        name = city["name"]
        log.info("[%d/%d] %s", i + 1, len(cities), name)
        tile = fetch_viirs_tile(name, city["bbox"], force=force)
        results[name] = {
            "mean_luminosity": round(float(tile.mean()), 2),
            "max_luminosity": round(float(tile.max()), 2),
            "status": "success",
            "file": str(VIIRS_DIR / f"{city_slug(name)}.npy"),
        }
        time.sleep(delay)

    summary_path = DATA_RAW / "viirs_all_cities.json"
    with open(summary_path, "w") as fh:
        json.dump(results, fh, indent=2)

    for name, row in results.items():
        log.info("  %-22s mean %5.1f  max %5.1f", name, row["mean_luminosity"], row["max_luminosity"])
    log.info("Summary written to %s", summary_path)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", type=str, help="fetch a single city")
    parser.add_argument("--force", action="store_true", help="download again even if cached")
    args = parser.parse_args()

    if args.city:
        city_bbox = CITY_BBOXES.get(args.city)
        if city_bbox:
            fetch_viirs_tile(args.city, city_bbox, force=args.force)
        else:
            log.error("Unknown city: %s", args.city)
    else:
        fetch_all_cities_viirs(force=args.force)
