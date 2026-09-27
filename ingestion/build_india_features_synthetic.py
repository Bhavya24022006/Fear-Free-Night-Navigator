"""
Fast synthetic feature stores for every city with a downloaded graph.

Instead of querying OSM and NASA per city, each edge's features are drawn
from priors that depend on its road class and its distance from the city
centre, scaled by the city's NCRB crime index:

  * lighting, lamps, shops, bus stops and police fall off towards the edge
    of the city and are higher on arterial roads;
  * crime rises on isolated, low-class roads and with the city index;
  * the time features describe 22:00, matching the real-data builder.

The PSI target uses the same formula as ingestion.fetch_all_features.

Run:
    python -m ingestion.build_india_features_synthetic                # all cities
    python -m ingestion.build_india_features_synthetic --city Mumbai
    python -m ingestion.build_india_features_synthetic --stats
"""

from __future__ import annotations

import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import osmnx as ox
import pandas as pd

from ai.ml.features import (
    DEFAULT_HIGHWAY_ENCODING,
    DEFAULT_HIGHWAY_LUMINOSITY,
    HIGHWAY_ENCODING,
    HIGHWAY_LUMINOSITY,
    MAJOR_ROAD_TYPES,
    city_slug,
    primary_highway,
    to_float,
)
from ingestion.fetch_crime_real import CITY_CRIME_INDEX
from ingestion.fetch_india_graph import CITY_BBOXES, INDIAN_CITIES, graph_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("build_india_features_synthetic")

FEAT_DIR = Path("data/india/features")
FEAT_DIR.mkdir(parents=True, exist_ok=True)

REFERENCE_HOUR = 22

# Typical number of nearby amenities for an edge of each road class.
HW_POIS = {
    "motorway":      {"shops": 0,  "lamps": 8, "bus_stops": 0, "police": 0},
    "trunk":         {"shops": 2,  "lamps": 6, "bus_stops": 1, "police": 0},
    "primary":       {"shops": 8,  "lamps": 5, "bus_stops": 3, "police": 1},
    "secondary":     {"shops": 12, "lamps": 4, "bus_stops": 4, "police": 1},
    "tertiary":      {"shops": 6,  "lamps": 2, "bus_stops": 2, "police": 0},
    "residential":   {"shops": 2,  "lamps": 1, "bus_stops": 1, "police": 0},
    "living_street": {"shops": 1,  "lamps": 0, "bus_stops": 0, "police": 0},
    "unclassified":  {"shops": 0,  "lamps": 0, "bus_stops": 0, "police": 0},
    "service":       {"shops": 0,  "lamps": 0, "bus_stops": 0, "police": 0},
}


def feature_store_path(city_name: str) -> Path:
    return FEAT_DIR / f"{city_slug(city_name)}_feature_store.csv"


def _edge_frame(G) -> pd.DataFrame:
    """Midpoint, road class and OSM attributes for every edge."""
    out_degree = dict(G.out_degree())
    in_degree = dict(G.in_degree())
    rows = []
    for u, v, k, data in G.edges(data=True, keys=True):
        try:
            u_lat, u_lon = to_float(G.nodes[u]["y"]), to_float(G.nodes[u]["x"])
            v_lat, v_lon = to_float(G.nodes[v]["y"]), to_float(G.nodes[v]["x"])
        except (KeyError, ValueError):
            continue
        rows.append({
            "u": u, "v": v, "key": k,
            "mid_lat": (u_lat + v_lat) / 2,
            "mid_lon": (u_lon + v_lon) / 2,
            "hw": primary_highway(data),
            "has_road_name": int(bool(data.get("name"))),
            "lanes": int(to_float(data.get("lanes", 1), 1)),
            "is_dead_end": int(out_degree[v] == 1 or in_degree[u] == 1),
            "name": str(data.get("name", "") or ""),
            "travel_time": to_float(data.get("travel_time", 60), 60),
            "length": to_float(data.get("length", 50), 50),
        })
    return pd.DataFrame(rows)


def _amenity_count(typical: np.ndarray, falloff: np.ndarray, extra: np.ndarray) -> np.ndarray:
    """Whole-number count: the road-class typical value reduced by distance, plus noise."""
    return np.maximum(0, (typical * falloff + extra).astype(int))


def build_synthetic_features_for_city(city_name: str, force: bool = False) -> pd.DataFrame:
    """Writes (or reuses) the synthetic feature store for one city."""
    out = feature_store_path(city_name)
    if out.exists() and not force:
        log.info("  %s: already built (%s)", city_name, out.name)
        try:
            df = pd.read_csv(out)
            log.info("  %s: %s edges loaded", city_name, f"{len(df):,}")
            return df
        except Exception:
            pass

    path = graph_path(city_name)
    if not path.exists():
        log.warning("  %s: no graph on disk, skipped", city_name)
        return pd.DataFrame()

    started = time.time()
    log.info("  %s: loading graph ...", city_name)
    G = ox.load_graphml(path)
    log.info("  %s: %s nodes, %s edges", city_name, f"{len(G.nodes):,}", f"{len(G.edges):,}")

    bbox = CITY_BBOXES.get(city_name, {})
    city_index = CITY_CRIME_INDEX.get(city_name, 0.40)
    centre_lat = (bbox.get("north", 13) + bbox.get("south", 12)) / 2
    centre_lon = (bbox.get("east", 78) + bbox.get("west", 77)) / 2
    max_dist = max(bbox.get("north", 13) - centre_lat, bbox.get("east", 78) - centre_lon)

    np.random.seed(abs(hash(city_name)) % 2**31)

    edges = _edge_frame(G)
    n = len(edges)
    hw = edges["hw"]
    hw_enc = hw.map(HIGHWAY_ENCODING).fillna(DEFAULT_HIGHWAY_ENCODING).to_numpy(float)
    base_lum = hw.map(HIGHWAY_LUMINOSITY).fillna(DEFAULT_HIGHWAY_LUMINOSITY).to_numpy(float)
    typical = {
        field: hw.map(lambda t: HW_POIS.get(t, HW_POIS["residential"])[field]).to_numpy(float)
        for field in ("shops", "lamps", "bus_stops", "police")
    }

    # 0 at the city centre, 1 at (or beyond) the edge of the bbox.
    offset = np.sqrt((edges["mid_lat"].to_numpy() - centre_lat) ** 2
                     + (edges["mid_lon"].to_numpy() - centre_lon) ** 2)
    dc = np.minimum(1.0, offset / max(max_dist, 0.01))

    # Illumination
    lum = np.clip(base_lum * (1 - dc * 0.4) + np.random.normal(0, 5, n), 5, 95)
    lamps = _amenity_count(typical["lamps"], 1 - dc * 0.5, np.random.poisson(1, n))
    major = hw.isin(list(MAJOR_ROAD_TYPES)).to_numpy()

    # Commercial activity and emergency services
    shops = _amenity_count(typical["shops"], 1 - dc * 0.6, np.random.poisson(2, n))
    police = _amenity_count(typical["police"], 1 - dc * 0.3,
                            (np.random.random(n) < 0.05).astype(int))
    commercial = np.clip(shops / 20 * 0.6 + police / 3 * 0.4 + np.random.normal(0, 0.05, n), 0, 1)
    emergency = np.clip(police / 3 * 0.7 + (np.random.random(n) < 0.03).astype(int) * 0.3, 0, 1)

    # Footfall and transit
    bus = _amenity_count(typical["bus_stops"], 1 - dc * 0.4, np.random.poisson(0.5, n))
    sidewalk = hw.isin(["primary", "secondary", "trunk"]).astype(int).to_numpy()
    footfall = np.clip(hw_enc * 0.5 + bus / 10 * 0.3 + sidewalk * 0.2
                       + np.random.normal(0, 0.05, n), 0, 1)
    transit = np.clip(bus / 5, 0, 1)

    # Crime: higher on isolated (low-class) roads and in high-index cities
    centre_term = city_index * (0.3 + dc * 0.3)
    isolation = 1 - hw_enc
    crime = np.clip(centre_term * 0.5 + isolation * city_index * 0.5
                    + np.random.normal(0, 0.03, n), 0.05, 0.92)
    night_crime = np.clip(crime * 1.45, 0.05, 0.95)
    accidents = np.clip(crime * 0.4, 0.02, 0.80)

    # Physical environment
    cctv = (hw.isin(["primary", "secondary"]).to_numpy()
            & (np.random.random(n) < 0.15)).astype(int)
    construction = (hw.str.lower().str.contains("construction").to_numpy()
                    | (np.random.random(n) < 0.02)).astype(int)

    # Visual environment
    brightness = np.clip(lum / 100 * 0.7 + np.random.beta(3, 2, n) * 0.3, 0.05, 0.95)
    darkness = np.clip((1 - lum / 100) * 0.5 + np.random.beta(2, 5, n) * 0.5, 0.02, 0.90)
    greenery = np.clip(dc * 0.3 + np.random.beta(2, 4, n) * 0.2, 0.01, 0.50)
    visual = np.clip(brightness * 0.5 + greenery * 0.2 - darkness * 0.4 + 0.3, 0.05, 0.95)

    # PSI target
    lum_norm = lum / 100
    psi = np.clip(
        28 * lum_norm + 22 * commercial + 18 * footfall + 15 * emergency
        - 17 * crime + visual * 10 + np.random.normal(0, 1.5, n),
        5.0, 95.0,
    )

    angle = 2 * np.pi * REFERENCE_HOUR / 24
    df = pd.DataFrame({
        "u": edges["u"], "v": edges["v"], "key": edges["key"], "city": city_name,
        # illumination
        "luminosity_score": np.round(lum, 2),
        "luminosity_norm": np.round(lum_norm, 3),
        "lamp_count_80m": lamps,
        "lamp_count_80m_norm": np.round(np.minimum(lamps / 10, 1), 3),
        "lit_road_bonus": major.astype(float),
        # commercial
        "commercial_score": np.round(commercial, 3),
        "emergency_score": np.round(emergency, 3),
        "shop_count_200m": shops,
        "shop_count_200m_norm": np.round(np.minimum(shops / 20, 1), 3),
        "police_count_500m": police,
        "police_count_500m_norm": np.round(np.minimum(police / 3, 1), 3),
        # footfall
        "footfall_score": np.round(footfall, 3),
        "transit_score": np.round(transit, 3),
        "bus_stop_count_300m": bus,
        "bus_stop_count_300m_norm": np.round(np.minimum(bus / 5, 1), 3),
        "is_primary_secondary": major.astype(int),
        "has_sidewalk": sidewalk,
        # crime
        "crime_penalty": np.round(crime, 3),
        "crime_density": np.round(crime, 3),
        "night_crime_density": np.round(night_crime, 3),
        "accident_density": np.round(accidents, 3),
        "combined_risk_score": np.round(crime * 100, 2),
        # physical
        "physical_score": np.round(hw_enc, 3),
        "is_dead_end": edges["is_dead_end"],
        "highway_type_enc": np.round(hw_enc, 3),
        "has_road_name": edges["has_road_name"],
        "lanes": edges["lanes"],
        "cctv_count_150m": cctv,
        "cctv_count_150m_norm": np.round(np.minimum(cctv / 5, 1), 3),
        "construction_nearby": construction,
        # visual
        "visual_score": np.round(visual, 3),
        "brightness_mean": np.round(brightness, 3),
        "darkness_ratio": np.round(darkness, 3),
        "greenery_ratio": np.round(greenery, 3),
        # time (reference hour)
        "hour_sin": float(np.sin(angle)),
        "hour_cos": float(np.cos(angle)),
        "is_night": 1,
        # target and graph attributes
        "safety_score": np.round(psi, 2),
        "highway": hw,
        "name": edges["name"],
        "travel_time": edges["travel_time"],
        "length": edges["length"],
    })
    df.to_csv(out, index=False)

    log.info("  %s: %s edges | mean safety %.1f | mean crime %.3f | %.0f s -> %s",
             city_name, f"{len(df):,}", df["safety_score"].mean(),
             df["crime_density"].mean(), time.time() - started, out.name)
    return df


def run_all_parallel(cities=None, max_workers: int = 4, force: bool = False) -> dict:
    """Builds the stores for every city with a graph, several at a time."""
    cities = cities or INDIAN_CITIES
    ready = []
    for city in cities:
        if graph_path(city["name"]).exists():
            ready.append(city)
        else:
            log.warning("  Skipping %s - graph not downloaded", city["name"])

    log.info("Building %d cities with %d workers ...", len(ready), max_workers)
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(build_synthetic_features_for_city, c["name"], force): c["name"]
                   for c in ready}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = len(future.result())
                log.info("  done: %s (%s edges)", name, f"{results[name]:,}")
            except Exception as exc:
                results[name] = 0
                log.error("  failed: %s (%s)", name, exc)

    log.info("Synthetic features complete: %d cities, %s edges, saved in %s",
             sum(1 for count in results.values() if count > 0),
             f"{sum(results.values()):,}", FEAT_DIR)
    return results


def print_stats():
    """Edge count and averages for every generated store."""
    stores = sorted(FEAT_DIR.glob("*_feature_store.csv"))
    if not stores:
        print("No feature stores generated yet.")
        return

    rule = "=" * 65
    print(f"\n{rule}\nFEATURE STORE COVERAGE\n{rule}")
    print(f"{'City':<22} {'Edges':>10} {'AvgScore':>9} {'AvgCrime':>9}")
    print("-" * 65)
    total = 0
    for store in stores:
        city = store.stem.replace("_feature_store", "").replace("_", " ").title()
        try:
            df = pd.read_csv(store)
        except Exception as exc:
            print(f"  {city:<20} ERROR: {exc}")
            continue
        total += len(df)
        print(f"  {city:<20} {len(df):>10,} {df['safety_score'].mean():>9.1f} "
              f"{df['crime_density'].mean():>9.3f}")
    print(rule)
    print(f"  {'TOTAL':<20} {total:>10,}")
    print(rule)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", type=str, help="build a single city")
    parser.add_argument("--all", action="store_true", help="build every city in parallel")
    parser.add_argument("--stats", action="store_true", help="print coverage statistics")
    parser.add_argument("--workers", type=int, default=4, help="parallel workers")
    parser.add_argument("--force", action="store_true", help="rebuild existing stores")
    args = parser.parse_args()

    if args.stats:
        print_stats()
    elif args.city:
        build_synthetic_features_for_city(args.city, force=args.force)
    else:
        run_all_parallel(max_workers=args.workers, force=args.force)
