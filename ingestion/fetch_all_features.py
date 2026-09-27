"""
Real-data feature pipeline: builds a city's feature store from open sources.

Signals gathered per city (all cached under data/india/features/):
    1. Illumination - NASA VIIRS night lights, OSM street lamps
    2. Commercial   - OSM shops, eateries, banks, ATMs, pharmacies
    3. Footfall     - OSM bus stops, stations, road class, sidewalks
    4. Crime        - NCRB-scaled crime zones (+ optional data.gov.in accidents)
    5. Physical     - OSM CCTV, police, hospitals, traffic calming, construction
    6. Visual       - Mapillary street imagery (optional) scored for brightness

Each road edge then gets counts and scores measured at its midpoint, and a
PSI safety target. The result is <city>_feature_store.csv.

Run:
    python -m ingestion.fetch_all_features                   # five largest metros
    python -m ingestion.fetch_all_features --city Mumbai
    python -m ingestion.fetch_all_features --all
    python -m ingestion.fetch_all_features --category crime # one signal only
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
import requests
from dotenv import load_dotenv
from scipy.spatial import cKDTree
from shapely.geometry import Point

from ai.ml.features import (
    DEFAULT_HIGHWAY_ENCODING,
    HIGHWAY_ENCODING,
    MAJOR_ROAD_TYPES,
    city_slug,
    primary_highway,
)
from ingestion.fetch_crime_real import CITY_CRIME_INDEX, build_crime_zones_for_city
from ingestion.fetch_india_graph import INDIAN_CITIES, graph_path

# Overpass settings shared by every OSM query in this module.
ox.settings.timeout = 60
ox.settings.max_query_area_size = 50 * 1000 * 50 * 1000
ox.settings.requests_pause = 1
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("fetch_all_features")

DATA_RAW = Path("data/raw")
FEAT_DIR = Path("data/india/features")
FEAT_DIR.mkdir(parents=True, exist_ok=True)

MAPILLARY_TOKEN = os.getenv("MAPILLARY_ACCESS_TOKEN", "")
OSMNX_VER = tuple(int(part) for part in ox.__version__.split(".")[:2])
DEGREES_PER_METRE = 1 / 111_320
DEFAULT_CITIES = ["Bengaluru", "Mumbai", "Delhi", "Chennai", "Hyderabad"]

# Search radius (m) and saturation count for each proximity feature.
POI_RADII = {"lamp": 80, "shop": 200, "bus": 300, "police": 500, "cctv": 150}
POI_CAPS = {"lamp": 10, "shop": 20, "bus": 5, "police": 3, "cctv": 5}

# Hour baked into the stored time features (the router adjusts for the real hour).
REFERENCE_HOUR = 22


def _cache_file(city_name: str, suffix: str) -> Path:
    return FEAT_DIR / f"{city_slug(city_name)}_{suffix}"


# OSM helpers ------------------------------------------------------------------

def _osm_features(bbox: dict, tags: dict) -> gpd.GeoDataFrame:
    """OSM features with the given tags inside the bbox (OSMnx 1.x or 2.x)."""
    if OSMNX_VER[0] >= 2:
        return ox.features_from_bbox(
            bbox=(bbox["west"], bbox["south"], bbox["east"], bbox["north"]),
            tags=tags,
        )
    return ox.features_from_bbox(
        north=bbox["north"], south=bbox["south"],
        east=bbox["east"], west=bbox["west"],
        tags=tags,
    )


def _point_of(geom) -> tuple[float, float]:
    """(lat, lon) of a geometry - the point itself or a polygon's centroid."""
    if geom.geom_type == "Point":
        return geom.y, geom.x
    centroid = geom.centroid
    return centroid.y, centroid.x


def _text(row, column: str) -> str:
    return str(row.get(column, "") or "")


def _to_points_gdf(records: list, empty_columns: list | None = None) -> gpd.GeoDataFrame:
    if not records and empty_columns is not None:
        return gpd.GeoDataFrame(columns=empty_columns)
    return gpd.GeoDataFrame(
        records,
        geometry=[Point(r["lon"], r["lat"]) for r in records],
        crs="EPSG:4326",
    )


def _fetch_poi_layer(city_name: str, bbox: dict, suffix: str, tags: dict,
                     describe, label: str) -> gpd.GeoDataFrame:
    """Downloads one OSM point layer, reduces it to points and caches it as GeoJSON.

    `describe(row)` returns the extra attributes stored for each feature.
    """
    out = _cache_file(city_name, suffix)
    if out.exists():
        return gpd.read_file(out)

    log.info("  [%s] Fetching %s ...", city_name, label)
    try:
        gdf = _osm_features(bbox, tags)
        records = []
        for _, row in gdf.iterrows():
            lat, lon = _point_of(row.geometry)
            records.append({"lat": round(lat, 6), "lon": round(lon, 6),
                            "city": city_name, **describe(row)})
        result = _to_points_gdf(records)
        result.to_file(out, driver="GeoJSON")
        log.info("  [%s] %s: %s", city_name, label, f"{len(result):,}")
        return result
    except Exception as exc:
        log.error("  [%s] %s failed: %s", city_name, label, exc)
        return gpd.GeoDataFrame()


# 1. Illumination ----------------------------------------------------------------

def fetch_street_lamps(city_name: str, bbox: dict) -> gpd.GeoDataFrame:
    """OSM street lamps, with up to three attempts (Overpass often times out)."""
    out = _cache_file(city_name, "street_lamps.geojson")
    if out.exists():
        return gpd.read_file(out)

    log.info("  [%s] Fetching street lamps ...", city_name)
    ox.settings.timeout = 60
    ox.settings.max_query_area_size = 50 * 1000 * 50 * 1000
    empty_columns = ["lat", "lon", "city", "geometry"]

    for attempt in range(3):
        try:
            gdf = _osm_features(bbox, {"highway": "street_lamp"})
            records = []
            for _, row in gdf.iterrows():
                if row.geometry is None:
                    continue
                lat, lon = _point_of(row.geometry)
                records.append({"lat": round(lat, 6), "lon": round(lon, 6), "city": city_name})
            result = _to_points_gdf(records, empty_columns)
            result.to_file(out, driver="GeoJSON")
            log.info("  [%s] Street lamps: %s", city_name, f"{len(result):,}")
            return result
        except Exception as exc:
            log.warning("  [%s] Street lamps attempt %d/3 failed: %s", city_name, attempt + 1, exc)
            if attempt < 2:
                wait = (attempt + 1) * 15
                log.info("  Retrying in %d s ...", wait)
                time.sleep(wait)

    log.warning("  [%s] Street lamps unavailable - saving an empty layer", city_name)
    empty = gpd.GeoDataFrame(columns=empty_columns)
    empty.to_file(out, driver="GeoJSON")
    return empty


def fetch_viirs_luminosity(city_name: str, bbox: dict) -> np.ndarray:
    """1024 x 1024 VIIRS brightness (0-100) from NASA GIBS, or a radial proxy."""
    viirs_dir = DATA_RAW / "viirs"
    viirs_dir.mkdir(exist_ok=True)
    out = viirs_dir / f"{city_slug(city_name)}.npy"
    if out.exists():
        return np.load(out)

    log.info("  [%s] Fetching VIIRS ...", city_name)
    area = f"&BBOX={bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"
    base = ("https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
            "?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS={layer}"
            "&CRS=EPSG:4326&FORMAT=image/png&WIDTH=1024&HEIGHT=1024")
    layers = ["VIIRS_Black_Marble", "VIIRS_SNPP_DayNightBand_At_Sensor_Radiance"]

    tile = None
    for layer in layers:
        try:
            from PIL import Image

            response = requests.get(base.format(layer=layer) + area, timeout=30)
            if response.status_code == 200 and len(response.content) > 5000:
                image = Image.open(io.BytesIO(response.content)).convert("L")
                tile = np.array(image, dtype=np.float32)
                if tile.max() > 0:
                    tile = tile / tile.max() * 100
                break
        except Exception as exc:
            log.warning("  VIIRS request failed: %s", exc)

    if tile is None:
        log.warning("  [%s] VIIRS unavailable - using the radial proxy", city_name)
        tile = _proxy_luminosity(bbox)

    np.save(out, tile)
    log.info("  [%s] VIIRS mean brightness %.1f", city_name, tile.mean())
    return tile


def _proxy_luminosity(bbox: dict) -> np.ndarray:
    """Brightness falling off linearly from the centre (80) to 1.5x the half-extent."""
    h = w = 1024
    centre_lat = (bbox["north"] + bbox["south"]) / 2
    centre_lon = (bbox["east"] + bbox["west"]) / 2
    max_r = max(bbox["north"] - centre_lat, bbox["east"] - centre_lon) * 1.5

    lats = bbox["north"] - np.arange(h) / h * (bbox["north"] - bbox["south"])
    lons = bbox["west"] + np.arange(w) / w * (bbox["east"] - bbox["west"])
    dist = np.sqrt((lats[:, None] - centre_lat) ** 2 + (lons[None, :] - centre_lon) ** 2)

    tile = np.maximum(0, 1 - dist / max_r) * 80 + np.random.uniform(0, 10, size=(h, w))
    return tile.astype(np.float32)


# 6. Visual (street imagery) ----------------------------------------------------

def fetch_mapillary_features(city_name: str, bbox: dict, max_imgs: int = 500) -> pd.DataFrame:
    """Per-image brightness, darkness and greenery from Mapillary thumbnails."""
    out = _cache_file(city_name, "mapillary.csv")
    if out.exists():
        return pd.read_csv(out)

    if not MAPILLARY_TOKEN:
        log.warning("  [%s] No Mapillary token - generating synthetic visual samples", city_name)
        return _synthetic_visual_features(city_name, bbox)

    log.info("  [%s] Fetching Mapillary images ...", city_name)
    params = {
        "access_token": MAPILLARY_TOKEN,
        "fields": "id,geometry,thumb_256_url,captured_at",
        "bbox": f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}",
        "limit": min(max_imgs, 2000),
    }
    try:
        response = requests.get("https://graph.mapillary.com/images", params=params, timeout=30)
        response.raise_for_status()
        images = response.json().get("data", [])
        log.info("  [%s] Mapillary returned %d images", city_name, len(images))
        if not images:
            return _synthetic_visual_features(city_name, bbox)

        records = []
        for image in images[:max_imgs]:
            coords = image.get("geometry", {}).get("coordinates", [0, 0])
            lon, lat = coords[0], coords[1]
            visual = _compute_visual_features_url(image.get("thumb_256_url", ""))
            records.append({
                "lat": round(float(lat), 6),
                "lon": round(float(lon), 6),
                "city": city_name,
                **visual,
                "captured_at": image.get("captured_at", ""),
            })
            time.sleep(0.1)

        df = pd.DataFrame(records)
        df.to_csv(out, index=False)
        log.info("  [%s] Visual features for %d images", city_name, len(df))
        return df
    except Exception as exc:
        log.error("  [%s] Mapillary failed: %s", city_name, exc)
        return _synthetic_visual_features(city_name, bbox)


def _compute_visual_features_url(url: str) -> dict:
    """Brightness, dark-pixel share and green-pixel share of one thumbnail."""
    fallback = {"brightness_mean": 0.35, "darkness_ratio": 0.30,
                "greenery_ratio": 0.10, "visual_score": 0.50}
    if not url:
        return fallback
    try:
        from PIL import Image

        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return fallback
        pixels = np.array(Image.open(io.BytesIO(response.content)).convert("RGB"),
                          dtype=np.float32) / 255.0
        red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]

        brightness = float(pixels.mean())
        darkness = float((pixels.mean(axis=2) < 0.15).mean())
        greenery = float(((green > red * 1.1) & (green > blue * 1.1) & (green > 0.15)).mean())
        visual = float(np.clip(brightness * 40 + greenery * 20 - darkness * 30 + 0.3, 0, 1))

        return {
            "brightness_mean": round(brightness, 3),
            "darkness_ratio": round(darkness, 3),
            "greenery_ratio": round(greenery, 3),
            "visual_score": round(visual, 3),
        }
    except Exception:
        return fallback


def _synthetic_visual_features(city_name: str, bbox: dict) -> pd.DataFrame:
    """200 random sample points with plausible visual statistics."""
    np.random.seed(abs(hash(city_name)) % 2**31)
    n = 200
    lats = np.random.uniform(bbox["south"], bbox["north"], n)
    lons = np.random.uniform(bbox["west"], bbox["east"], n)
    df = pd.DataFrame({
        "lat": np.round(lats, 6),
        "lon": np.round(lons, 6),
        "city": city_name,
        "brightness_mean": np.random.beta(3, 2, n).round(3),
        "darkness_ratio": np.random.beta(2, 5, n).round(3),
        "greenery_ratio": np.random.beta(2, 4, n).round(3),
        "visual_score": np.random.beta(3, 2, n).round(3),
    })
    df.to_csv(_cache_file(city_name, "mapillary.csv"), index=False)
    return df


def _heuristic_visual_scores(images: pd.DataFrame, city_name: str) -> pd.DataFrame:
    """Visual safety score from brightness, greenery and darkness of each image."""
    records = []
    for _, row in images.iterrows():
        brightness = float(row.get("brightness_mean", 0.35))
        darkness = float(row.get("darkness_ratio", 0.30))
        greenery = float(row.get("greenery_ratio", 0.10))
        score = float(np.clip(brightness * 0.5 + greenery * 0.2 - darkness * 0.4 + 0.3, 0, 1))
        records.append({
            "lat": row["lat"],
            "lon": row["lon"],
            "city": city_name,
            "clip_score": round(score, 3),
            "brightness": round(brightness, 3),
            "darkness": round(darkness, 3),
            "greenery": round(greenery, 3),
        })
    return pd.DataFrame(records)


def compute_clip_scores(mapillary_df: pd.DataFrame, city_name: str,
                        batch_size: int = 16) -> pd.DataFrame:
    """Visual safety score per image.

    Loads CLIP ViT-B/32 and encodes "safe" and "unsafe" street descriptions
    when the package is installed; the stored score itself is the
    brightness / greenery / darkness heuristic in both cases.
    """
    out = _cache_file(city_name, "clip_scores.csv")
    if out.exists():
        return pd.read_csv(out)

    log.info("  [%s] Scoring street imagery ...", city_name)
    try:
        import clip
        import torch
    except ImportError:
        log.warning("  [%s] CLIP not installed - using the visual heuristic", city_name)
        scores = _heuristic_visual_scores(mapillary_df, city_name)
        scores.to_csv(out, index=False)
        return scores

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _preprocess = clip.load("ViT-B/32", device=device)
    safe_prompts = [
        "a brightly lit street at night that feels safe",
        "a lively shopping street with stores open",
        "a street with streetlights and footpaths",
        "a city road with a police presence",
        "a well-kept road lined with street lamps",
    ]
    unsafe_prompts = [
        "a dark, empty alley at night",
        "a deserted road where the streetlights are broken",
        "an abandoned street that looks unsafe",
        "a badly lit road with nobody walking",
        "a threatening, dark part of a city",
    ]
    with torch.no_grad():
        model.encode_text(clip.tokenize(safe_prompts).to(device)).mean(dim=0)
        model.encode_text(clip.tokenize(unsafe_prompts).to(device)).mean(dim=0)

    scores = _heuristic_visual_scores(mapillary_df, city_name)
    scores.to_csv(out, index=False)
    log.info("  [%s] Visual scores: %d", city_name, len(scores))
    return scores


# 2. Commercial, 3. Transit, 5. Physical -----------------------------------------

def fetch_commercial_pois(city_name: str, bbox: dict) -> gpd.GeoDataFrame:
    """Shops, eateries, banks, ATMs, pharmacies and retail land use."""
    tags = {
        "amenity": ["restaurant", "cafe", "bar", "fast_food", "food_court",
                    "bank", "atm", "pharmacy", "supermarket"],
        "shop": True,
        "landuse": ["retail", "commercial"],
    }
    return _fetch_poi_layer(
        city_name, bbox, "commercial.geojson", tags,
        lambda row: {"amenity": _text(row, "amenity"), "shop": _text(row, "shop"),
                     "landuse": _text(row, "landuse"), "name": _text(row, "name")},
        "commercial POIs",
    )


def fetch_transit_pois(city_name: str, bbox: dict) -> gpd.GeoDataFrame:
    """Bus stops, stations and platforms."""
    tags = {
        "highway": "bus_stop",
        "public_transport": ["stop_position", "platform", "station"],
        "railway": ["station", "halt", "tram_stop"],
        "amenity": "bus_station",
    }

    def describe(row):
        kind = (row.get("highway", "") or row.get("public_transport", "")
                or row.get("railway", "") or "stop")
        return {"type": str(kind), "name": _text(row, "name")}

    return _fetch_poi_layer(city_name, bbox, "transit.geojson", tags, describe, "transit stops")


def fetch_physical_features(city_name: str, bbox: dict) -> gpd.GeoDataFrame:
    """CCTV, traffic calming, police, hospitals, fire stations, construction."""
    tags = {
        "man_made": "surveillance",
        "traffic_calming": True,
        "amenity": ["police", "hospital", "fire_station", "clinic"],
        "emergency": True,
        "construction": True,
    }

    def describe(row):
        amenity = _text(row, "amenity")
        if _text(row, "man_made") == "surveillance":
            kind = "cctv"
        elif _text(row, "traffic_calming"):
            kind = "speed_bump"
        elif amenity == "police":
            kind = "police"
        elif amenity in ("hospital", "clinic"):
            kind = "hospital"
        elif amenity == "fire_station":
            kind = "fire_station"
        else:
            kind = "other"
        return {"feat_type": kind, "name": _text(row, "name")}

    return _fetch_poi_layer(city_name, bbox, "physical.geojson", tags, describe, "physical features")


# 4. Crime -------------------------------------------------------------------------

_STATE_OF_CITY = {
    "Bengaluru": "Karnataka", "Chennai": "Tamil Nadu", "Hyderabad": "Telangana",
    "Mumbai": "Maharashtra", "Delhi": "Delhi", "Kolkata": "West Bengal",
    "Pune": "Maharashtra", "Ahmedabad": "Gujarat", "Jaipur": "Rajasthan",
    "Lucknow": "Uttar Pradesh", "Kochi": "Kerala", "Chandigarh": "Punjab",
    "Bhopal": "Madhya Pradesh", "Indore": "Madhya Pradesh", "Patna": "Bihar",
    "Ranchi": "Jharkhand", "Guwahati": "Assam", "Bhubaneswar": "Odisha",
}


def _city_to_state(city_name: str) -> str:
    """State filter value for data.gov.in (empty when unknown)."""
    return _STATE_OF_CITY.get(city_name, "")


def fetch_crime_data(city_name: str, bbox: dict) -> pd.DataFrame:
    """Incident points for inspection: data.gov.in accidents plus zone samples.

    The accident records carry no coordinates, so they are placed at random
    inside the bbox. Zone samples scatter int(density x 50) points around each
    crime-zone centre.
    """
    out = _cache_file(city_name, "crime.csv")
    if out.exists():
        return pd.read_csv(out)

    log.info("  [%s] Collecting crime data ...", city_name)
    records = []

    try:
        response = requests.get(
            "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070",
            params={
                "api-key": "579b464db66ec23bdd000001cdd3946e44ce4aab825ef2a0abf7b1b4",
                "format": "json",
                "limit": "100",
                "filters[State_UT]": _city_to_state(city_name),
            },
            timeout=15,
        )
        if response.status_code == 200:
            payload = response.json()
            if "records" in payload:
                for record in payload["records"]:
                    records.append({
                        "lat": float(bbox["south"] + np.random.uniform(0, bbox["north"] - bbox["south"])),
                        "lon": float(bbox["west"] + np.random.uniform(0, bbox["east"] - bbox["west"])),
                        "type": "accident",
                        "severity": str(record.get("Severity", "moderate")),
                        "year": str(record.get("Year", "2022")),
                        "city": city_name,
                        "source": "data.gov.in",
                    })
                log.info("  [%s] data.gov.in accident records: %d", city_name, len(records))
    except Exception as exc:
        log.warning("  [%s] data.gov.in request failed: %s", city_name, exc)

    zones = build_crime_zones_for_city(city_name, bbox)
    np.random.seed(abs(hash(city_name)) % 2**31)

    for zone in zones:
        spread = zone["r"] / 111320
        for _ in range(int(zone["d"] * 50)):
            lat = zone["lat"] + np.random.normal(0, spread)
            lon = zone["lon"] + np.random.normal(0, spread)
            if bbox["south"] <= lat <= bbox["north"] and bbox["west"] <= lon <= bbox["east"]:
                records.append({
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "type": "crime",
                    "severity": "high" if zone["d"] > 0.7 else "moderate",
                    "year": "2022",
                    "city": city_name,
                    "source": "NCRB_2022_model",
                    "zone": zone.get("name", ""),
                })

    df = pd.DataFrame(records)
    if not df.empty:
        df.to_csv(out, index=False)
    log.info("  [%s] Crime records: %s", city_name, f"{len(df):,}")
    return df


# Feature store --------------------------------------------------------------------

def _parse_lanes(value) -> int:
    """OSM lane count; 1 when missing or not a plain number."""
    try:
        return int(value or 1)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 1


def _edge_table(G) -> pd.DataFrame:
    """One row per edge with its midpoint and OSM attributes."""
    rows = []
    for u, v, k, data in G.edges(data=True, keys=True):
        try:
            u_lat, u_lon = float(G.nodes[u]["y"]), float(G.nodes[u]["x"])
            v_lat, v_lon = float(G.nodes[v]["y"]), float(G.nodes[v]["x"])
        except (KeyError, ValueError):
            continue

        highway = primary_highway(data)
        rows.append({
            "u": u,
            "v": v,
            "key": k,
            "mid_lat": (u_lat + v_lat) / 2,
            "mid_lon": (u_lon + v_lon) / 2,
            "hw": highway,
            "hw_enc": HIGHWAY_ENCODING.get(highway, DEFAULT_HIGHWAY_ENCODING),
            "has_sidewalk": int(str(data.get("sidewalk", "no")).lower()
                                in ("both", "left", "right", "yes")),
            "has_road_name": int(bool(data.get("name"))),
            "lanes": _parse_lanes(data.get("lanes", 1)),
            "lit_tag": int(str(data.get("lit", "no")).lower()
                           in ("yes", "24/7", "sunset-sunrise")),
            "is_dead_end": int(G.out_degree(v) == 1 or G.in_degree(u) == 1),
            "travel_time": float(data.get("travel_time", 60) or 60),
            "length": float(data.get("length", 50) or 50),
            "name": str(data.get("name", "") or ""),
        })
    return pd.DataFrame(rows)


def _count_within(lats: np.ndarray, lons: np.ndarray, points, radius_m: float) -> np.ndarray:
    """Number of points within radius_m of each (lat, lon) - one KD-tree query."""
    if points is None or len(points) == 0:
        return np.zeros(len(lats), dtype=int)
    tree = cKDTree(np.column_stack([points.geometry.y.values, points.geometry.x.values]))
    counts = tree.query_ball_point(np.column_stack([lats, lons]),
                                   radius_m * DEGREES_PER_METRE, return_length=True)
    return np.array(counts, dtype=int)


def _zone_envelope(lats: np.ndarray, lons: np.ndarray, zones: list, floor: float) -> np.ndarray:
    """Strongest Gaussian crime-zone influence at each point, at least `floor`."""
    density = np.full(len(lats), floor)
    for zone in zones:
        dist_m = np.sqrt((lats - zone["lat"]) ** 2 + (lons - zone["lon"]) ** 2) / DEGREES_PER_METRE
        impact = zone["d"] * np.exp(-0.5 * (dist_m / max(zone["r"] * 0.5, 1)) ** 2)
        density = np.maximum(density, impact)
    return density


def build_city_feature_store(city_name: str, bbox: dict, force: bool = False) -> pd.DataFrame:
    """Computes every feature for every edge of the city and saves the store."""
    out = _cache_file(city_name, "feature_store.csv")
    if force:
        stale = (list(FEAT_DIR.glob(f"{city_slug(city_name)}*.geojson"))
                 + list(FEAT_DIR.glob(f"{city_slug(city_name)}*.csv")))
        for path in stale:
            path.unlink()
            log.info("  Removed %s", path.name)
    if out.exists():
        log.info("  [%s] Feature store already built.", city_name)
        return pd.read_csv(out)

    log.info("Building features for %s", city_name)
    path = graph_path(city_name)
    if not path.exists():
        log.error("Graph not found: %s", path)
        return pd.DataFrame()
    G = ox.load_graphml(path)
    log.info("  Graph: %s nodes, %s edges", f"{len(G.nodes):,}", f"{len(G.edges):,}")

    # Gather every source (each call is cached on disk).
    lamps = fetch_street_lamps(city_name, bbox)
    viirs = fetch_viirs_luminosity(city_name, bbox)
    imagery = fetch_mapillary_features(city_name, bbox)
    visual = compute_clip_scores(imagery, city_name)
    commercial = fetch_commercial_pois(city_name, bbox)
    transit = fetch_transit_pois(city_name, bbox)
    fetch_crime_data(city_name, bbox)
    physical = fetch_physical_features(city_name, bbox)

    df = _edge_table(G)
    log.info("  %s edges to score", f"{len(df):,}")
    lats, lons = df["mid_lat"].values, df["mid_lon"].values

    # Illumination: pixel of the VIIRS tile under each midpoint.
    h, w = viirs.shape
    lat_span = max(bbox["north"] - bbox["south"], 1e-6)
    lon_span = max(bbox["east"] - bbox["west"], 1e-6)
    rows = ((bbox["north"] - df["mid_lat"]) / lat_span * h).astype(int).clip(0, h - 1)
    cols = ((df["mid_lon"] - bbox["west"]) / lon_span * w).astype(int).clip(0, w - 1)
    df["luminosity_score"] = viirs[rows.values, cols.values]
    df["luminosity_norm"] = (df["luminosity_score"] / 100).clip(0, 1)

    # Crime: zone envelope plus a little noise.
    floor = CITY_CRIME_INDEX.get(city_name, 0.35) * 0.3
    zones = build_crime_zones_for_city(city_name, bbox)
    crime = _zone_envelope(lats, lons, zones, floor)
    df["crime_density"] = (crime + np.random.normal(0, 0.02, len(df))).clip(0.05, 0.95)
    df["night_crime_density"] = (df["crime_density"] * 1.35).clip(0.05, 0.95)
    df["accident_density"] = (df["crime_density"] * 0.4).clip(0.02, 0.80)
    df["combined_risk_score"] = (df["crime_density"] * 100).round(2)
    df["crime_penalty"] = df["crime_density"]

    # Proximity counts.
    if physical is not None and len(physical) > 0 and "feat_type" in physical.columns:
        police = physical[physical["feat_type"] == "police"]
        cctv = physical[physical["feat_type"] == "cctv"]
    else:
        police = cctv = gpd.GeoDataFrame()

    for name, layer, column in [
        ("lamp", lamps, "lamp_count_80m"),
        ("shop", commercial, "shop_count_200m"),
        ("bus", transit, "bus_stop_count_300m"),
        ("police", police, "police_count_500m"),
        ("cctv", cctv, "cctv_count_150m"),
    ]:
        df[column] = _count_within(lats, lons, layer, POI_RADII[name])
        df[f"{column}_norm"] = (df[column] / POI_CAPS[name]).clip(0, 1)

    # Visual: attributes of the nearest scored image.
    if visual is not None and len(visual) > 0:
        tree = cKDTree(np.column_stack([visual["lat"].values, visual["lon"].values]))
        _, nearest = tree.query(np.column_stack([lats, lons]), k=1)
        df["visual_score"] = visual["clip_score"].values[nearest]
        df["brightness_mean"] = visual["brightness"].values[nearest]
        df["darkness_ratio"] = visual["darkness"].values[nearest]
        df["greenery_ratio"] = visual["greenery"].values[nearest]
    else:
        df["visual_score"], df["brightness_mean"] = 0.50, 0.35
        df["darkness_ratio"], df["greenery_ratio"] = 0.30, 0.10

    # Composite scores.
    df["commercial_score"] = (df["shop_count_200m_norm"] * 0.6
                              + df["police_count_500m_norm"] * 0.4).clip(0, 1)
    df["emergency_score"] = (df["police_count_500m_norm"] * 0.7
                             + (df["police_count_500m"] > 0).astype(float) * 0.3).clip(0, 1)
    df["footfall_score"] = (df["hw_enc"] * 0.5 + df["bus_stop_count_300m_norm"] * 0.3
                            + df["has_sidewalk"] * 0.2).clip(0, 1)
    df["transit_score"] = df["bus_stop_count_300m_norm"]
    df["physical_score"] = df["hw_enc"]
    df["is_primary_secondary"] = df["hw"].isin(list(MAJOR_ROAD_TYPES)).astype(int)
    df["construction_nearby"] = df["hw"].str.contains("construction", na=False).astype(int)

    angle = 2 * np.pi * REFERENCE_HOUR / 24
    df["hour_sin"] = float(np.sin(angle))
    df["hour_cos"] = float(np.cos(angle))
    df["is_night"] = 1

    # PSI target.
    df["safety_score"] = np.clip(
        28 * df["luminosity_norm"]
        + 22 * df["commercial_score"]
        + 18 * df["footfall_score"]
        + 15 * df["emergency_score"]
        - 17 * df["crime_density"]
        + df["visual_score"] * 10
        + np.random.normal(0, 1.5, len(df)),
        5.0, 95.0,
    ).round(2)

    df["city"] = city_name
    df["highway"] = df["hw"]
    df.to_csv(out, index=False)

    log.info("Finished %s: %s edges | mean safety %.1f | mean luminosity %.1f | mean crime %.3f -> %s",
             city_name, f"{len(df):,}", df["safety_score"].mean(),
             df["luminosity_score"].mean(), df["crime_density"].mean(), out)
    return df


# Command line ---------------------------------------------------------------------

_CATEGORY_STEPS = {
    "illumination": (fetch_street_lamps, fetch_viirs_luminosity, fetch_mapillary_features),
    "commercial": (fetch_commercial_pois,),
    "transit": (fetch_transit_pois,),
    "crime": (fetch_crime_data,),
    "physical": (fetch_physical_features,),
}


def run(city: str = None, category: str = None, all_cities: bool = False, force: bool = False):
    if city:
        match = next((c for c in INDIAN_CITIES if c["name"].lower() == city.lower()), None)
        if match is None:
            log.error("Unknown city: %s", city)
            return
        targets = [match]
    elif all_cities:
        targets = INDIAN_CITIES
    else:
        targets = [c for c in INDIAN_CITIES if c["name"] in DEFAULT_CITIES]

    log.info("Processing %d cities ...", len(targets))
    for i, target in enumerate(targets):
        name, bbox = target["name"], target["bbox"]
        log.info("[%d/%d] %s", i + 1, len(targets), name)
        try:
            if category in _CATEGORY_STEPS:
                for step in _CATEGORY_STEPS[category]:
                    step(name, bbox)
            else:
                build_city_feature_store(name, bbox, force=force)
        except Exception as exc:
            log.error("  %s failed: %s", name, exc)
    log.info("All requested cities processed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", type=str, help="process a single city")
    parser.add_argument("--category", type=str, help="fetch one signal only")
    parser.add_argument("--all", action="store_true", help="process every city")
    parser.add_argument("--force", action="store_true", help="rebuild even if cached")
    args = parser.parse_args()

    run(city=args.city, category=args.category, all_cities=args.all, force=args.force)
