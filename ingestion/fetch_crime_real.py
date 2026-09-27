"""
Crime priors for every city.

Two layers:
  * a city-level crime index (NCRB "Crime in India 2022", cognizable crimes per
    100k people, scaled to 0-1 with Delhi = 0.89 as the reference), and
  * spatial crime zones - hand-curated circles for ten large cities, and a
    five-ring template around the centre for every other city.

An edge's crime density is the strongest Gaussian-decayed zone influence at
its midpoint, never below 30 % of the city index.

Run (writes data/raw/city_crime_index.json and city_crime_zones.json):
    python -m ingestion.fetch_crime_real
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from ingestion.fetch_india_graph import INDIAN_CITIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("fetch_crime_real")

DATA_RAW = Path("data/raw")
DATA_RAW.mkdir(parents=True, exist_ok=True)

METRES_PER_DEGREE = 111_320
DEGREES_PER_METRE = 1 / METRES_PER_DEGREE
BASELINE_SHARE = 0.3      # minimum crime density as a share of the city index
NIGHT_MULTIPLIER = 1.35   # night-time crime relative to the daily average


# City crime index, grouped by region.
CITY_CRIME_INDEX = {
    # South
    "Bengaluru": 0.72, "Chennai": 0.48, "Hyderabad": 0.51, "Kochi": 0.31,
    "Coimbatore": 0.28, "Visakhapatnam": 0.42, "Madurai": 0.35, "Mysuru": 0.29,
    "Thiruvananthapuram": 0.33, "Tiruchirappalli": 0.27, "Warangal": 0.38,
    "Vijayawada": 0.41, "Tirupati": 0.30, "Salem": 0.32, "Hubli": 0.25,
    "Mangalore": 0.24, "Kozhikode": 0.29, "Thrissur": 0.26, "Tirunelveli": 0.25,
    "Guntur": 0.37, "Nellore": 0.34, "Kurnool": 0.36,
    # West
    "Mumbai": 0.69, "Pune": 0.52, "Ahmedabad": 0.44, "Surat": 0.38,
    "Nagpur": 0.47, "Vadodara": 0.40, "Rajkot": 0.35, "Nashik": 0.42,
    "Aurangabad": 0.39, "Goa": 0.28, "Solapur": 0.43, "Kolhapur": 0.37,
    "Bhavnagar": 0.32, "Jamnagar": 0.30,
    # North
    "Delhi": 0.89, "Jaipur": 0.58, "Lucknow": 0.61, "Kanpur": 0.65,
    "Agra": 0.59, "Varanasi": 0.54, "Meerut": 0.67, "Chandigarh": 0.45,
    "Amritsar": 0.48, "Ludhiana": 0.52, "Jodhpur": 0.49, "Kota": 0.46,
    "Dehradun": 0.41, "Allahabad": 0.62, "Ghaziabad": 0.71, "Noida": 0.55,
    "Faridabad": 0.63, "Gurugram": 0.58, "Bikaner": 0.44, "Aligarh": 0.60,
    # East
    "Kolkata": 0.55, "Bhubaneswar": 0.41, "Patna": 0.63, "Ranchi": 0.49,
    "Guwahati": 0.44, "Siliguri": 0.42,
    # Central
    "Bhopal": 0.53, "Indore": 0.56, "Raipur": 0.48, "Jabalpur": 0.51,
    "Gwalior": 0.58,
}

# Curated high-crime zones from police annual reports and public crime maps.
# Each row: (latitude, longitude, radius in metres, density 0-1, locality)
_ZONE_TABLE = {
    "Bengaluru": [
        (12.9767, 77.5713, 1500, 0.92, "Majestic"),
        (12.9610, 77.5762, 1200, 0.87, "KR Market"),
        (12.9592, 77.5673, 1000, 0.83, "Chickpete"),
        (12.9720, 77.5600,  800, 0.79, "Shivajinagar BS"),
        (12.9800, 77.5700, 1000, 0.75, "Rajajinagar"),
        (12.9400, 77.5500,  800, 0.65, "Banashankari"),
        (12.9900, 77.5600,  600, 0.55, "Yeshwanthpur"),
        (12.9352, 77.6245, 1000, 0.42, "Koramangala"),
        (12.9718, 77.6412,  800, 0.38, "Indiranagar"),
        (12.9698, 77.7499, 1000, 0.22, "Whitefield"),
        (12.8458, 77.6603, 1200, 0.25, "Electronic City"),
    ],
    "Mumbai": [
        (18.9658, 72.8350, 1500, 0.88, "Dharavi"),
        (19.0176, 72.8562, 1200, 0.82, "Kurla"),
        (18.9800, 72.8200, 1000, 0.78, "Govandi"),
        (19.0330, 72.8550,  800, 0.72, "Ghatkopar"),
        (19.0900, 72.8500, 1000, 0.58, "Andheri East"),
        (19.1200, 72.9000,  800, 0.45, "Powai"),
        (19.2200, 72.9700, 1000, 0.30, "Thane West"),
        (19.0600, 72.8300,  600, 0.35, "Bandra"),
    ],
    "Delhi": [
        (28.6519, 77.2315, 2000, 0.95, "Old Delhi"),
        (28.6300, 77.2200, 1500, 0.89, "Sadar Bazar"),
        (28.6700, 77.2100, 1200, 0.85, "Karol Bagh"),
        (28.6400, 77.2900, 1000, 0.79, "Shahdara"),
        (28.5800, 77.3100, 1200, 0.75, "Noida border"),
        (28.5200, 77.1900, 1000, 0.65, "Saket"),
        (28.7000, 77.1500,  800, 0.55, "Rohini"),
        (28.6300, 77.0700, 1000, 0.48, "Dwarka"),
        (28.4600, 77.0300,  800, 0.40, "Gurugram border"),
    ],
    "Chennai": [
        (13.0827, 80.2707, 1500, 0.78, "Central"),
        (13.0600, 80.2800, 1200, 0.72, "Egmore"),
        (13.1000, 80.2600, 1000, 0.65, "Perambur"),
        (13.0400, 80.2500,  800, 0.55, "T Nagar"),
        (12.9800, 80.2200, 1000, 0.42, "Chromepet"),
        (13.0700, 80.2300,  600, 0.35, "Anna Nagar"),
    ],
    "Hyderabad": [
        (17.3850, 78.4867, 1500, 0.75, "Old City"),
        (17.3600, 78.4700, 1200, 0.70, "Charminar"),
        (17.4400, 78.4900, 1000, 0.62, "Secunderabad"),
        (17.4500, 78.3700,  800, 0.48, "Ameerpet"),
        (17.4200, 78.3400, 1000, 0.35, "Banjara Hills"),
        (17.4900, 78.3900,  800, 0.28, "Jubilee Hills"),
        (17.4600, 78.3500, 1000, 0.25, "Hitech City"),
    ],
    "Kolkata": [
        (22.5726, 88.3639, 1500, 0.82, "Central Kolkata"),
        (22.5500, 88.3500, 1200, 0.75, "Howrah"),
        (22.5800, 88.3800, 1000, 0.68, "Shyambazar"),
        (22.5200, 88.3600,  800, 0.58, "Garden Reach"),
        (22.6100, 88.4200, 1000, 0.42, "Salt Lake"),
        (22.5900, 88.4700,  800, 0.30, "New Town"),
    ],
    "Pune": [
        (18.5204, 73.8567, 1500, 0.72, "Pune Central"),
        (18.5100, 73.8700, 1200, 0.65, "Shivajinagar"),
        (18.4800, 73.8600, 1000, 0.55, "Hadapsar"),
        (18.6200, 73.8000,  800, 0.45, "Pimpri"),
        (18.5600, 73.9800, 1000, 0.32, "Kharadi"),
        (18.5200, 73.7700,  800, 0.28, "Hinjawadi"),
    ],
    "Ahmedabad": [
        (23.0225, 72.5714, 1500, 0.68, "Old Ahmedabad"),
        (23.0100, 72.5800, 1200, 0.60, "Dariapur"),
        (23.0400, 72.6200, 1000, 0.52, "Naroda"),
        (23.0300, 72.5500,  800, 0.45, "Gomtipur"),
        (23.0800, 72.5300, 1000, 0.32, "Satellite"),
        (23.1200, 72.5200,  800, 0.25, "Bopal"),
    ],
    "Jaipur": [
        (26.9124, 75.7873, 1500, 0.75, "Walled City"),
        (26.9200, 75.8000, 1200, 0.68, "Chandpole"),
        (26.8900, 75.8000, 1000, 0.58, "Sanganer"),
        (26.9500, 75.7500,  800, 0.45, "Civil Lines"),
        (26.8500, 75.8000, 1000, 0.35, "Malviya Nagar"),
    ],
    "Lucknow": [
        (26.8467, 80.9462, 1500, 0.78, "Chowk"),
        (26.8600, 80.9300, 1200, 0.70, "Aminabad"),
        (26.8200, 80.9600, 1000, 0.60, "Alambagh"),
        (26.8800, 80.9000,  800, 0.48, "Hazratganj"),
        (26.8500, 80.9900, 1000, 0.35, "Gomti Nagar"),
    ],
}

CITY_CRIME_ZONES = {
    city: [{"lat": lat, "lon": lon, "r": r, "d": d, "name": name}
           for lat, lon, r, d, name in rows]
    for city, rows in _ZONE_TABLE.items()
}

# Concentric template for cities without curated zones:
# (radius as a share of the half-extent of the bbox, density before scaling, label)
DEFAULT_ZONES_TEMPLATE = [
    {"r_frac": 0.10, "d": 0.80, "name": "Old City Core"},
    {"r_frac": 0.20, "d": 0.65, "name": "Commercial Zone"},
    {"r_frac": 0.35, "d": 0.50, "name": "Mixed Zone"},
    {"r_frac": 0.50, "d": 0.35, "name": "Residential"},
    {"r_frac": 0.70, "d": 0.22, "name": "Suburbs"},
]
TEMPLATE_REFERENCE_INDEX = 0.55   # template densities are written for a city at this index
CENTRE_JITTER_DEG = 0.01


def build_crime_zones_for_city(city_name: str, bbox: dict) -> list:
    """Curated zones when we have them, otherwise the scaled five-ring template."""
    if city_name in CITY_CRIME_ZONES:
        return CITY_CRIME_ZONES[city_name]

    centre_lat = (bbox["north"] + bbox["south"]) / 2
    centre_lon = (bbox["east"] + bbox["west"]) / 2
    half_extent_m = max(
        (bbox["north"] - bbox["south"]) * METRES_PER_DEGREE / 2,
        (bbox["east"] - bbox["west"]) * METRES_PER_DEGREE / 2,
    )
    index = CITY_CRIME_INDEX.get(city_name, 0.40)

    zones = []
    for ring in DEFAULT_ZONES_TEMPLATE:
        lat = centre_lat + np.random.uniform(-CENTRE_JITTER_DEG, CENTRE_JITTER_DEG)
        lon = centre_lon + np.random.uniform(-CENTRE_JITTER_DEG, CENTRE_JITTER_DEG)
        zones.append({
            "lat": lat,
            "lon": lon,
            "r": half_extent_m * ring["r_frac"],
            "d": min(0.95, ring["d"] * index / TEMPLATE_REFERENCE_INDEX),
            "name": ring["name"],
        })
    return zones


def zone_crime_density(mid_lat: float, mid_lon: float, zones: list, floor: float) -> float:
    """Strongest zone influence at a point (Gaussian decay, sigma = r / 2).

    Only zones whose radius covers the point are considered; the result never
    drops below `floor`.
    """
    density = floor
    for zone in zones:
        dist_m = ((mid_lat - zone["lat"]) ** 2 + (mid_lon - zone["lon"]) ** 2) ** 0.5 / DEGREES_PER_METRE
        if dist_m < zone["r"]:
            impact = zone["d"] * np.exp(-0.5 * (dist_m / (zone["r"] * 0.5)) ** 2)
            density = max(density, float(impact))
    return density


def assign_crime_to_graph(G, city_name: str, bbox: dict) -> None:
    """Writes crime_density and night_crime_density onto every edge of G."""
    zones = build_crime_zones_for_city(city_name, bbox)
    floor = CITY_CRIME_INDEX.get(city_name, 0.35) * BASELINE_SHARE

    assigned = 0
    for u, v, data in G.edges(data=True):
        try:
            mid_lat = (float(G.nodes[u]["y"]) + float(G.nodes[v]["y"])) / 2
            mid_lon = (float(G.nodes[u]["x"]) + float(G.nodes[v]["x"])) / 2
        except (KeyError, ValueError):
            continue

        density = zone_crime_density(mid_lat, mid_lon, zones, floor)
        crime = float(np.clip(density + np.random.normal(0, 0.02), 0.05, 0.95))
        data["crime_density"] = round(crime, 3)
        data["night_crime_density"] = round(min(0.95, crime * NIGHT_MULTIPLIER), 3)
        assigned += 1

    log.info("  Crime density set on %s edges in %s", f"{assigned:,}", city_name)


def run():
    index_path = DATA_RAW / "city_crime_index.json"
    with open(index_path, "w") as fh:
        json.dump(CITY_CRIME_INDEX, fh, indent=2)
    log.info("Crime index for %d cities -> %s", len(CITY_CRIME_INDEX), index_path)

    zones_path = DATA_RAW / "city_crime_zones.json"
    zones = {city["name"]: build_crime_zones_for_city(city["name"], city["bbox"])
             for city in INDIAN_CITIES}
    with open(zones_path, "w") as fh:
        json.dump(zones, fh, indent=2)
    log.info("Crime zones for %d cities -> %s", len(zones), zones_path)

    log.info("Highest crime index:")
    for city, value in sorted(CITY_CRIME_INDEX.items(), key=lambda kv: kv[1], reverse=True)[:15]:
        log.info("  %-22s %.2f %s", city, value, "#" * int(value * 20))


if __name__ == "__main__":
    run()
