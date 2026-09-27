"""
City catalogue and OpenStreetMap road-graph download.

Each city has a bounding box sized to cover its whole metropolitan or district
area. For every city we download the drivable road network with OSMnx, add
edge speeds and travel times, and save it as GraphML.

Run:
    python -m ingestion.fetch_india_graph --all          # every city
    python -m ingestion.fetch_india_graph --city Mumbai  # one city
    python -m ingestion.fetch_india_graph --stats        # coverage summary
    python -m ingestion.fetch_india_graph                # the five largest metros
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import osmnx as ox
from dotenv import load_dotenv

from ai.ml.features import city_slug

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("fetch_india_graph")

DATA_INDIA = Path("data/india")
CITY_GRAPHS = DATA_INDIA / "city_graphs"
CITY_GRAPHS.mkdir(parents=True, exist_ok=True)

OSMNX_VER = tuple(int(part) for part in ox.__version__.split(".")[:2])

DEFAULT_CITIES = ["Bengaluru", "Mumbai", "Delhi", "Chennai", "Hyderabad"]
REQUEST_DELAY_S = 8.0   # pause between Overpass downloads


# name, state, population, (north, south, east, west) in decimal degrees
_CITY_TABLE = [
    # South
    ("Bengaluru",          "Karnataka",      "13.6M", (13.35, 12.65, 77.95, 77.25)),
    ("Chennai",            "Tamil Nadu",     "10.9M", (13.40, 12.75, 80.45, 79.95)),
    ("Hyderabad",          "Telangana",      "10.5M", (17.70, 17.05, 78.85, 78.15)),
    ("Kochi",              "Kerala",         "2.1M",  (10.25,  9.75, 76.55, 76.05)),
    ("Coimbatore",         "Tamil Nadu",     "2.2M",  (11.25, 10.75, 77.25, 76.75)),
    ("Visakhapatnam",      "Andhra Pradesh", "2.0M",  (17.95, 17.45, 83.50, 82.95)),
    ("Madurai",            "Tamil Nadu",     "1.6M",  (10.15,  9.65, 78.40, 77.90)),
    ("Mysuru",             "Karnataka",      "1.2M",  (12.55, 12.05, 76.95, 76.45)),
    ("Thiruvananthapuram", "Kerala",         "1.7M",  ( 8.75,  8.25, 77.25, 76.75)),
    ("Tiruchirappalli",    "Tamil Nadu",     "1.1M",  (11.05, 10.65, 78.95, 78.45)),
    # West (Mumbai covers the MMR; Pune includes Pimpri-Chinchwad; Ahmedabad reaches Gandhinagar)
    ("Mumbai",             "Maharashtra",    "20.7M", (19.45, 18.75, 73.25, 72.65)),
    ("Pune",               "Maharashtra",    "6.6M",  (18.85, 18.25, 74.20, 73.55)),
    ("Ahmedabad",          "Gujarat",        "8.4M",  (23.30, 22.75, 72.90, 72.30)),
    ("Surat",              "Gujarat",        "6.6M",  (21.45, 20.90, 73.15, 72.60)),
    ("Nagpur",             "Maharashtra",    "2.9M",  (21.40, 20.85, 79.35, 78.80)),
    ("Vadodara",           "Gujarat",        "2.3M",  (22.55, 22.05, 73.45, 72.95)),
    ("Rajkot",             "Gujarat",        "1.8M",  (22.50, 22.05, 71.00, 70.55)),
    ("Nashik",             "Maharashtra",    "1.9M",  (20.20, 19.75, 74.10, 73.60)),
    ("Aurangabad",         "Maharashtra",    "1.4M",  (20.10, 19.65, 75.55, 75.05)),
    ("Goa",                "Goa",            "0.7M",  (15.80, 15.00, 74.10, 73.60)),
    # North (Delhi covers the NCR; Chandigarh includes Mohali and Panchkula)
    ("Delhi",              "Delhi",          "32.9M", (29.10, 28.20, 77.60, 76.60)),
    ("Jaipur",             "Rajasthan",      "3.9M",  (27.25, 26.60, 76.10, 75.50)),
    ("Lucknow",            "Uttar Pradesh",  "3.8M",  (27.20, 26.55, 81.30, 80.70)),
    ("Kanpur",             "Uttar Pradesh",  "3.1M",  (26.70, 26.20, 80.70, 80.10)),
    ("Agra",               "Uttar Pradesh",  "1.8M",  (27.40, 26.95, 78.35, 77.85)),
    ("Varanasi",           "Uttar Pradesh",  "1.6M",  (25.55, 25.15, 83.25, 82.75)),
    ("Meerut",             "Uttar Pradesh",  "1.7M",  (29.15, 28.70, 77.95, 77.45)),
    ("Chandigarh",         "Punjab",         "1.2M",  (30.95, 30.55, 77.05, 76.65)),
    ("Amritsar",           "Punjab",         "1.3M",  (31.85, 31.45, 75.15, 74.65)),
    ("Ludhiana",           "Punjab",         "1.8M",  (31.10, 30.65, 76.10, 75.65)),
    # East (Kolkata covers Howrah, Salt Lake and New Town; Bhubaneswar includes Cuttack)
    ("Kolkata",            "West Bengal",    "14.8M", (22.95, 22.20, 88.65, 88.05)),
    ("Bhubaneswar",        "Odisha",         "1.0M",  (20.55, 20.05, 86.10, 85.60)),
    ("Patna",              "Bihar",          "2.5M",  (25.85, 25.35, 85.50, 84.90)),
    ("Ranchi",             "Jharkhand",      "1.4M",  (23.60, 23.10, 85.65, 85.10)),
    ("Guwahati",           "Assam",          "1.4M",  (26.40, 25.95, 92.10, 91.50)),
    ("Siliguri",           "West Bengal",    "0.7M",  (26.90, 26.55, 88.60, 88.25)),
    # Central
    ("Bhopal",             "Madhya Pradesh", "2.4M",  (23.50, 23.00, 77.70, 77.15)),
    ("Indore",             "Madhya Pradesh", "3.3M",  (23.00, 22.45, 76.20, 75.65)),
    ("Raipur",             "Chhattisgarh",   "1.2M",  (21.50, 21.00, 82.00, 81.40)),
    ("Jabalpur",           "Madhya Pradesh", "1.4M",  (23.35, 22.90, 80.25, 79.70)),
    ("Gwalior",            "Madhya Pradesh", "1.2M",  (26.45, 25.95, 78.50, 77.95)),
    # Other state and district centres (Hubli includes Dharwad)
    ("Dehradun",           "Uttarakhand",    "0.8M",  (30.55, 30.10, 78.25, 77.80)),
    ("Jodhpur",            "Rajasthan",      "1.4M",  (26.50, 26.05, 73.25, 72.80)),
    ("Kota",               "Rajasthan",      "1.2M",  (25.35, 24.90, 76.05, 75.60)),
    ("Vijayawada",         "Andhra Pradesh", "1.5M",  (16.75, 16.25, 80.90, 80.35)),
    ("Warangal",           "Telangana",      "0.8M",  (18.20, 17.75, 79.80, 79.30)),
    ("Tirupati",           "Andhra Pradesh", "0.5M",  (13.85, 13.45, 79.65, 79.25)),
    ("Salem",              "Tamil Nadu",     "0.9M",  (11.85, 11.45, 78.35, 77.90)),
    ("Hubli",              "Karnataka",      "0.9M",  (15.55, 15.10, 75.35, 74.90)),
    ("Mangalore",          "Karnataka",      "0.6M",  (13.10, 12.70, 75.10, 74.70)),
]

INDIAN_CITIES = [
    {
        "name": name,
        "state": state,
        "bbox": {"north": north, "south": south, "east": east, "west": west},
        "pop": population,
    }
    for name, state, population, (north, south, east, west) in _CITY_TABLE
]

CITY_BBOXES = {city["name"]: city["bbox"] for city in INDIAN_CITIES}


def graph_path(city_name: str) -> Path:
    """Where the GraphML file for a city lives."""
    return CITY_GRAPHS / f"{city_slug(city_name)}.graphml"


def _download_drive_graph(bbox: dict):
    """Drivable network inside the bbox, largest connected component only."""
    options = dict(network_type="drive", retain_all=False, simplify=True)
    if OSMNX_VER[0] >= 2:
        return ox.graph_from_bbox(
            bbox=(bbox["west"], bbox["south"], bbox["east"], bbox["north"]),
            **options,
        )
    return ox.graph_from_bbox(
        north=bbox["north"], south=bbox["south"],
        east=bbox["east"], west=bbox["west"],
        **options,
    )


def fetch_city_graph(city: dict, force: bool = False):
    """Downloads (or reuses) one city's graph; returns it, or None on failure."""
    name = city["name"]
    out = graph_path(name)

    if out.exists() and not force:
        log.info("  %s: already on disk", name)
        try:
            return ox.load_graphml(out)
        except Exception:
            log.warning("  %s: stored file is unreadable, downloading again", name)

    log.info("  Downloading %s, %s (population %s) ...", name, city["state"], city["pop"])
    try:
        G = _download_drive_graph(city["bbox"])
        G = ox.add_edge_speeds(G)
        G = ox.add_edge_travel_times(G)
        G.graph.update(city=name, state=city["state"], pop=city["pop"])

        ox.save_graphml(G, out)
        log.info("  %s: %s nodes, %s edges -> %s",
                 name, f"{len(G.nodes):,}", f"{len(G.edges):,}", out.name)
        return G
    except Exception as exc:
        log.error("  %s: download failed (%s)", name, exc)
        return None


def _summary(G, city: dict, status: str) -> dict:
    return {
        "status": status,
        "nodes": len(G.nodes),
        "edges": len(G.edges),
        "state": city["state"],
        "pop": city["pop"],
    }


def fetch_all_cities(cities=None, delay: float = REQUEST_DELAY_S, force: bool = False):
    """Downloads several cities in turn and writes city_metadata.json."""
    cities = cities or INDIAN_CITIES
    results = {}
    counts = {"success": 0, "skipped": 0, "failed": 0}

    log.info("Fetching %d city graphs (about %.0f min including pauses) ...",
             len(cities), len(cities) * delay / 60)

    for i, city in enumerate(cities):
        name = city["name"]
        log.info("[%d/%d] %s, %s", i + 1, len(cities), name, city["state"])

        if graph_path(name).exists() and not force:
            counts["skipped"] += 1
            try:
                results[name] = _summary(ox.load_graphml(graph_path(name)), city, "cached")
            except Exception:
                results[name] = {"status": "cached"}
            continue

        G = fetch_city_graph(city, force=force)
        if G is None:
            counts["failed"] += 1
            results[name] = {"status": "failed"}
        else:
            counts["success"] += 1
            results[name] = {**_summary(G, city, "success"), "bbox": city["bbox"]}

        if i < len(cities) - 1:
            log.info("  Pausing %.0f s ...", delay)
            time.sleep(delay)

    meta_path = DATA_INDIA / "city_metadata.json"
    with open(meta_path, "w") as fh:
        json.dump(results, fh, indent=2)

    log.info("Done - downloaded %(success)d, reused %(skipped)d, failed %(failed)d", counts)
    log.info("Metadata written to %s", meta_path)
    return results


def get_available_cities() -> list:
    """Cities that have a GraphML file on disk."""
    return [p.stem.replace("_", " ").title() for p in sorted(CITY_GRAPHS.glob("*.graphml"))]


def load_city_graph(city_name: str):
    """Loads a city's graph, or returns None if it has not been downloaded."""
    path = graph_path(city_name)
    if not path.exists():
        return None
    log.info("Loading %s", city_name)
    return ox.load_graphml(path)


def _bbox_centre(bbox: dict) -> tuple[float, float]:
    return (bbox["north"] + bbox["south"]) / 2, (bbox["east"] + bbox["west"]) / 2


def find_city_for_coordinates(lat: float, lon: float) -> str:
    """City whose bbox contains the point, else the city with the nearest centre."""
    for city in INDIAN_CITIES:
        bbox = city["bbox"]
        if bbox["south"] <= lat <= bbox["north"] and bbox["west"] <= lon <= bbox["east"]:
            return city["name"]

    def distance(city):
        c_lat, c_lon = _bbox_centre(city["bbox"])
        return ((lat - c_lat) ** 2 + (lon - c_lon) ** 2) ** 0.5

    return min(INDIAN_CITIES, key=distance)["name"] if INDIAN_CITIES else "Bengaluru"


def print_stats():
    """Prints node and edge counts for every downloaded city."""
    cities = get_available_cities()
    meta_path = DATA_INDIA / "city_metadata.json"
    if not meta_path.exists() or not cities:
        print("No cities downloaded yet.")
        print("Run: python -m ingestion.fetch_india_graph --all")
        return

    with open(meta_path) as fh:
        meta = json.load(fh)
    ok = {name: row for name, row in meta.items() if row.get("status") in ("success", "cached")}

    total_nodes = sum(row.get("nodes", 0) for row in ok.values())
    total_edges = sum(row.get("edges", 0) for row in ok.values())
    states = {row.get("state", "") for row in ok.values()}

    rule = "=" * 65
    print(f"\n{rule}\nFEAR-FREE NAVIGATOR - ROAD GRAPH COVERAGE\n{rule}")
    print(f"  Cities covered : {len(cities)}")
    print(f"  States covered : {len(states)}")
    print(f"  Total nodes    : {total_nodes:,}")
    print(f"  Total edges    : {total_edges:,}")
    print(f"  Avg edges/city : {total_edges // max(len(cities), 1):,}")
    print(rule)
    print(f"\n{'City':<22} {'State':<22} {'Pop':<8} {'Nodes':>8} {'Edges':>8}")
    print("-" * 65)
    for name, row in sorted(ok.items(), key=lambda item: item[1].get("edges", 0), reverse=True):
        print(f"  {name:<20} {row.get('state', ''):<22} {row.get('pop', '?'):<8} "
              f"{row.get('nodes', 0):>8,} {row.get('edges', 0):>8,}")
    print(rule)


def run(city=None, all_cities=False, stats=False, force=False):
    if stats:
        print_stats()
        return

    if city:
        match = next((c for c in INDIAN_CITIES if c["name"].lower() == city.lower()), None)
        if match is None:
            log.error("Unknown city '%s'. Known cities: %s",
                      city, [c["name"] for c in INDIAN_CITIES])
            return
        fetch_city_graph(match, force=force)
        return

    if all_cities:
        fetch_all_cities(force=force)
    else:
        log.info("No option given - fetching the five largest metros.")
        fetch_all_cities(cities=[c for c in INDIAN_CITIES if c["name"] in DEFAULT_CITIES])
    print_stats()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download road graphs for Indian cities")
    parser.add_argument("--city", type=str, help="download a single city")
    parser.add_argument("--all", action="store_true", help="download every city")
    parser.add_argument("--stats", action="store_true", help="print coverage statistics")
    parser.add_argument("--force", action="store_true", help="re-download existing graphs")
    args = parser.parse_args()

    run(city=args.city, all_cities=args.all, stats=args.stats, force=args.force)
