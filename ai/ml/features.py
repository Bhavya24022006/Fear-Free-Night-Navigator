"""
Shared definitions for road-segment features.

The ingestion builders, the trainer, the inference helpers and the router all
import from here, so the column order, fallback values and road-type lookups
are defined exactly once.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# Model input columns, grouped by the safety signal they describe.
# The trained model depends on this exact order - append, never reorder.
FEATURE_GROUPS: dict[str, list[str]] = {
    "illumination": [
        "luminosity_score", "luminosity_norm", "lamp_count_80m_norm", "lit_road_bonus",
    ],
    "commercial": [
        "commercial_score", "emergency_score", "shop_count_200m_norm", "police_count_500m_norm",
    ],
    "footfall": [
        "footfall_score", "transit_score", "bus_stop_count_300m_norm",
        "is_primary_secondary", "has_sidewalk",
    ],
    "crime": [
        "crime_penalty", "crime_density", "night_crime_density",
        "accident_density", "combined_risk_score",
    ],
    "physical": [
        "physical_score", "is_dead_end", "highway_type_enc", "has_road_name",
        "lanes", "cctv_count_150m_norm", "construction_nearby",
    ],
    "visual": [
        "visual_score", "brightness_mean", "darkness_ratio", "greenery_ratio",
    ],
    "time": [
        "hour_sin", "hour_cos", "is_night",
    ],
}

FEATURE_COLS: list[str] = [col for cols in FEATURE_GROUPS.values() for col in cols]

# Value used for a feature that an edge does not carry.
FEATURE_DEFAULTS: dict[str, float] = {
    "luminosity_score": 35.0,
    "luminosity_norm": 0.35,
    "lamp_count_80m_norm": 0.0,
    "lit_road_bonus": 0.3,
    "commercial_score": 0.3,
    "emergency_score": 0.1,
    "shop_count_200m_norm": 0.2,
    "police_count_500m_norm": 0.0,
    "footfall_score": 0.4,
    "transit_score": 0.2,
    "bus_stop_count_300m_norm": 0.1,
    "is_primary_secondary": 0,
    "has_sidewalk": 0,
    "crime_penalty": 0.2,
    "crime_density": 0.15,
    "night_crime_density": 0.20,
    "accident_density": 0.10,
    "combined_risk_score": 20.0,
    "physical_score": 0.5,
    "is_dead_end": 0,
    "highway_type_enc": 0.42,
    "has_road_name": 1,
    "lanes": 1,
    "cctv_count_150m_norm": 0.0,
    "construction_nearby": 0,
    "visual_score": 0.5,
    "brightness_mean": 0.35,
    "darkness_ratio": 0.30,
    "greenery_ratio": 0.10,
    "hour_sin": 0.0,
    "hour_cos": -1.0,
    "is_night": 1,
}

# Road hierarchy as a 0-1 safety proxy: busier, better-kept roads score higher.
HIGHWAY_ENCODING: dict[str, float] = {
    "motorway": 0.95, "trunk": 0.90, "primary": 0.85, "secondary": 0.75,
    "tertiary": 0.60, "residential": 0.42, "living_street": 0.30,
    "unclassified": 0.22, "service": 0.18,
}
DEFAULT_HIGHWAY_ENCODING = 0.35

# Typical night brightness (0-100) per road type, used when no satellite tile exists.
HIGHWAY_LUMINOSITY: dict[str, float] = {
    "motorway": 88, "trunk": 82, "primary": 75, "secondary": 65,
    "tertiary": 50, "residential": 38, "living_street": 28,
    "unclassified": 25, "service": 20,
}
DEFAULT_HIGHWAY_LUMINOSITY = 35

# Road types treated as major arterials.
MAJOR_ROAD_TYPES = ("primary", "secondary", "trunk", "motorway")

# Plain-language meaning of each feature, used when explaining a score.
FEATURE_DESCRIPTIONS: dict[str, str] = {
    "luminosity_score": "night-time brightness seen by satellite",
    "luminosity_norm": "satellite brightness scaled to 0-1",
    "lamp_count_80m_norm": "street lamps within 80 m",
    "lit_road_bonus": "road marked as lit",
    "commercial_score": "shops and eateries close by",
    "emergency_score": "police stations and hospitals close by",
    "shop_count_200m_norm": "shops within 200 m",
    "police_count_500m_norm": "police stations within 500 m",
    "footfall_score": "expected pedestrian activity",
    "transit_score": "access to public transport",
    "bus_stop_count_300m_norm": "bus stops within 300 m",
    "is_primary_secondary": "major, high-traffic road",
    "has_sidewalk": "separate footpath available",
    "crime_penalty": "crime risk (higher means riskier)",
    "crime_density": "recorded crime density in the area",
    "night_crime_density": "night-time crime density in the area",
    "accident_density": "closeness to road-accident hotspots",
    "combined_risk_score": "crime and accident risk combined",
    "physical_score": "quality of the physical road setting",
    "is_dead_end": "dead-end, isolated road",
    "highway_type_enc": "road class (arterial roads rank higher)",
    "has_road_name": "named road that people know and use",
    "lanes": "lane count (more lanes, more traffic)",
    "cctv_count_150m_norm": "CCTV cameras within 150 m",
    "construction_nearby": "construction work nearby",
    "visual_score": "how safe the street looks in imagery",
    "brightness_mean": "average image brightness",
    "darkness_ratio": "share of very dark image pixels",
    "greenery_ratio": "share of vegetation in view",
    "hour_sin": "time of day (sine part)",
    "hour_cos": "time of day (cosine part)",
    "is_night": "night flag (8 PM to 6 AM)",
}


def to_float(value, default: float = 0.0) -> float:
    """Converts a value to float, falling back when it cannot be parsed.

    GraphML stores every attribute as text, so edge values arrive as strings.
    """
    try:
        return float(value)
    except Exception:
        return float(default)


def primary_highway(edge_data: dict, default: str = "residential") -> str:
    """Returns the edge's road type; OSM sometimes lists several, keep the first."""
    highway = edge_data.get("highway", default)
    if isinstance(highway, list):
        highway = highway[0]
    return str(highway)


def city_slug(city_name: str) -> str:
    """File-name form of a city name, e.g. 'New Town' -> 'new_town'."""
    return city_name.lower().replace(" ", "_")


def make_time_features(hour: int) -> dict:
    """Encodes the hour on a circle so 23:00 and 00:00 end up next to each other."""
    angle = 2 * np.pi * hour / 24
    return {
        "hour_sin": float(np.sin(angle)),
        "hour_cos": float(np.cos(angle)),
        "is_night": int(hour >= 20 or hour <= 5),
    }


def get_time_period(hour: int) -> str:
    """Coarse label for an hour, used in logs and messages."""
    if 6 <= hour < 20:
        return "day"
    if 20 <= hour < 23:
        return "evening"
    if hour == 23 or hour < 3:
        return "night"
    return "late_night"


def _feature_row(edge_data: dict, time_feats: dict) -> dict:
    row = {}
    for col in FEATURE_COLS:
        if col in edge_data:
            row[col] = edge_data[col]
        elif col in time_feats:
            row[col] = time_feats[col]
        else:
            row[col] = FEATURE_DEFAULTS.get(col, 0.0)
    return row


def build_feature_vector(edge_data: dict, hour: int = 22) -> pd.DataFrame:
    """One-row model input for a single edge; missing values use FEATURE_DEFAULTS."""
    row = _feature_row(edge_data, make_time_features(hour))
    return pd.DataFrame([row])[FEATURE_COLS]


def build_feature_vectors_batch(edges: list[dict], hour: int = 22) -> pd.DataFrame:
    """Model input for many edges at once (NaN cells become 0)."""
    time_feats = make_time_features(hour)
    rows = [_feature_row(edge_data, time_feats) for edge_data in edges]
    return pd.DataFrame(rows)[FEATURE_COLS].fillna(0)


def normalise_count(value: float, max_val: float) -> float:
    """Scales a count into 0-1, saturating at max_val."""
    return float(np.clip(value / max_val, 0.0, 1.0))


def get_feature_description(feature_name: str) -> str:
    """Human-readable name of a feature (falls back to the column name)."""
    return FEATURE_DESCRIPTIONS.get(feature_name, feature_name.replace("_", " "))
