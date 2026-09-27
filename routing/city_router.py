"""
Multi-city routing engine.

For a requested city this module
  1. loads the road graph (cached in memory for an hour),
  2. writes luminosity, crime density and an ML safety score onto every edge,
  3. re-weights the edges for the requested hour, travel mode and safety
     preference, and
  4. runs Dijkstra twice - once on the safety-aware cost, once on travel time.

Loading a large city takes a while, so the work checks a "generation" number:
when the user switches to another city, loads for the old city stop early.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

from ai.ml.features import (
    DEFAULT_HIGHWAY_ENCODING,
    DEFAULT_HIGHWAY_LUMINOSITY,
    FEATURE_COLS,
    HIGHWAY_ENCODING,
    HIGHWAY_LUMINOSITY,
    city_slug,
    primary_highway,
    to_float,
)
from ai.ml.predict import score_to_color, score_to_grade

log = logging.getLogger("routing.city_router")

DATA_RAW = Path("data/raw")
DATA_INDIA = Path("data/india")
CITY_GRAPHS = DATA_INDIA / "city_graphs"
FEATURE_DIR = DATA_INDIA / "features"
DATA_PROC = Path("data/processed")
VIIRS_DIR = DATA_RAW / "viirs"
ARTIFACTS = Path("ai/ml/artifacts")

CACHE_TTL = 3600            # seconds a scored city graph stays in memory
CHECK_EVERY = 2000          # edges between cancellation checks
LOCK_POLL_S = 0.5           # how often a waiting request re-checks cancellation
FALLBACK_SAFETY = 40.0      # score for edges missing from the feature store
FALLBACK_LUMINOSITY = 35.0
DANGEROUS_BELOW = 20        # temporal safety under this counts as dangerous
HIGH_RISK_BELOW = 40        # temporal safety under this (grades D and E) counts as high risk
WORTH_IT_MINUTES = 5        # extra minutes still considered a small cost
WORTH_IT_POINTS = 15        # safety gain that justifies any extra time
BLOCKED_WEIGHT = 9999.0


class CityPipelineCancelled(RuntimeError):
    """A newer request for a different city has replaced this one."""


# Active-city bookkeeping -------------------------------------------------------

class _PipelineRegistry:
    """Tracks which city is currently being served.

    The generation number only moves when the city changes, so several
    requests for the same city share one generation and none cancels another.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._city: str | None = None
        self._generation = 0
        self._build_locks: dict[str, threading.Lock] = {}
        self._build_locks_guard = threading.RLock()

    def begin(self, city_name: str) -> int:
        with self._lock:
            if self._city != city_name:
                self._city = city_name
                self._generation += 1
                log.info("Active city is now %s (generation %s)", city_name, self._generation)
            return self._generation

    def ensure_active(self, city_name: str, generation: int | None) -> None:
        if generation is None:
            return
        with self._lock:
            active_city, active_generation = self._city, self._generation
        if active_city != city_name or active_generation != generation:
            raise CityPipelineCancelled(
                f"Stopped outdated work for {city_name} "
                f"(generation {generation}; active {active_city}/{active_generation})"
            )

    def build_lock(self, city_name: str) -> threading.Lock:
        with self._build_locks_guard:
            return self._build_locks.setdefault(city_name, threading.Lock())


_pipelines = _PipelineRegistry()
_graph_cache: dict[str, object] = {}
_graph_cache_time: dict[str, float] = {}


def begin_latest_city_pipeline(city_name: str) -> int:
    """Marks city_name as the city being served and returns its generation id."""
    return _pipelines.begin(city_name)


def _assert_pipeline_active(city_name: str, pipeline_generation: int | None):
    _pipelines.ensure_active(city_name, pipeline_generation)


def _edges_with_checks(G, city_name, generation, keys=False):
    """Iterates edges, checking for cancellation every CHECK_EVERY edges."""
    for i, edge in enumerate(G.edges(data=True, keys=keys)):
        if city_name is not None and i % CHECK_EVERY == 0:
            _assert_pipeline_active(city_name, generation)
        yield edge


def _cached_graph(city_name: str, now: float):
    if city_name in _graph_cache and now - _graph_cache_time.get(city_name, 0) < CACHE_TTL:
        return _graph_cache[city_name]
    return None


def _remember(city_name: str, G, now: float):
    _graph_cache[city_name] = G
    _graph_cache_time[city_name] = now
    return G


# Data sources --------------------------------------------------------------------

def _load_crime_index() -> dict:
    path = DATA_RAW / "city_crime_index.json"
    if path.exists():
        with open(path) as fh:
            return json.load(fh)
    from ingestion.fetch_crime_real import CITY_CRIME_INDEX
    return CITY_CRIME_INDEX


def _load_crime_zones(city_name: str) -> list:
    path = DATA_RAW / "city_crime_zones.json"
    if path.exists():
        with open(path) as fh:
            return json.load(fh).get(city_name, [])
    from ingestion.fetch_crime_real import build_crime_zones_for_city
    from ingestion.fetch_india_graph import CITY_BBOXES
    return build_crime_zones_for_city(city_name, CITY_BBOXES.get(city_name, {}))


def _load_viirs(city_name: str) -> np.ndarray | None:
    path = VIIRS_DIR / f"{city_slug(city_name)}.npy"
    return np.load(path) if path.exists() else None


def _midpoint(G, u, v) -> tuple[float, float]:
    lat = (to_float(G.nodes[u]["y"]) + to_float(G.nodes[v]["y"])) / 2
    lon = (to_float(G.nodes[u]["x"]) + to_float(G.nodes[v]["x"])) / 2
    return lat, lon


# Graph loading ---------------------------------------------------------------------

def _load_bengaluru_fallback(city_name: str, now: float):
    """Legacy single-city graphs, used when no multi-city graph file exists."""
    for candidate in (DATA_PROC / "bengaluru_scored_graph.graphml",
                      DATA_RAW / "bengaluru_graph.graphml"):
        if candidate.exists():
            log.info("Loading legacy graph %s", candidate)
            G = ox.load_graphml(candidate)
            log.info("  %s: %s nodes, %s edges", city_name, f"{len(G.nodes):,}", f"{len(G.edges):,}")
            return _remember(city_name, G, now)
    raise FileNotFoundError("No graph found. Run the ingestion scripts first.")


def load_city_graph(city_name: str, pipeline_generation: int | None = None):
    """Scored graph for a city, loading and scoring it on first use.

    Only one thread builds a given city; other requests for it wait for the
    build and then reuse the cached result.
    """
    _assert_pipeline_active(city_name, pipeline_generation)
    cached = _cached_graph(city_name, time.time())
    if cached is not None:
        return cached

    build_lock = _pipelines.build_lock(city_name)
    while True:
        _assert_pipeline_active(city_name, pipeline_generation)
        if build_lock.acquire(timeout=LOCK_POLL_S):
            break

    try:
        now = time.time()
        cached = _cached_graph(city_name, now)
        if cached is not None:
            return cached

        path = CITY_GRAPHS / f"{city_slug(city_name)}.graphml"
        if not path.exists():
            log.warning("No graph for %s; falling back to Bengaluru.", city_name)
            if city_name != "Bengaluru":
                return load_city_graph("Bengaluru")
            return _load_bengaluru_fallback(city_name, now)

        if city_name == "Bengaluru":
            scored = DATA_PROC / "bengaluru_scored_graph.graphml"
            if scored.exists() and scored.stat().st_mtime > path.stat().st_mtime:
                log.info("Using pre-scored graph %s", scored)
                G = ox.load_graphml(scored)
                log.info("  %s: %s nodes, %s edges", city_name, f"{len(G.nodes):,}", f"{len(G.edges):,}")
                return _remember(city_name, G, now)

        log.info("Loading %s", city_name)
        G = ox.load_graphml(path)
        log.info("  %s: %s nodes, %s edges", city_name, f"{len(G.nodes):,}", f"{len(G.edges):,}")
        G = _inject_all_scores(G, city_name, pipeline_generation=pipeline_generation)
        return _remember(city_name, G, now)
    finally:
        build_lock.release()


def _inject_all_scores(G, city_name: str, pipeline_generation: int | None = None):
    """Adds luminosity, crime density and safety score to every edge."""
    from ingestion.fetch_india_graph import CITY_BBOXES

    bbox = CITY_BBOXES.get(city_name)
    _assert_pipeline_active(city_name, pipeline_generation)

    viirs = _load_viirs(city_name)
    if viirs is not None and bbox:
        log.info("  Adding VIIRS luminosity ...")
        _inject_viirs(G, viirs, bbox, city_name, pipeline_generation)
    else:
        log.info("  No VIIRS tile - using the road-type luminosity proxy ...")
        _inject_luminosity_proxy(G, city_name=city_name, pipeline_generation=pipeline_generation)

    log.info("  Adding crime density ...")
    _inject_crime_density(G, city_name, bbox, pipeline_generation=pipeline_generation)

    log.info("  Adding safety scores ...")
    _inject_safety_scores(G, city_name, pipeline_generation=pipeline_generation)
    return G


def _inject_viirs(G, viirs: np.ndarray, bbox: dict, city_name: str, generation) -> None:
    h, w = viirs.shape
    lat_span = bbox["north"] - bbox["south"]
    lon_span = bbox["east"] - bbox["west"]
    for u, v, data in _edges_with_checks(G, city_name, generation):
        try:
            mid_lat, mid_lon = _midpoint(G, u, v)
            row = int((bbox["north"] - mid_lat) / lat_span * h)
            col = int((mid_lon - bbox["west"]) / lon_span * w)
            row = max(0, min(row, h - 1))
            col = max(0, min(col, w - 1))
            data["luminosity_score"] = round(float(viirs[row, col]), 2)
        except Exception:
            data["luminosity_score"] = FALLBACK_LUMINOSITY


def _inject_luminosity_proxy(G, city_name: str | None = None,
                             pipeline_generation: int | None = None):
    """Typical brightness for the road type, +/- 5, on edges that have none."""
    for u, v, data in _edges_with_checks(G, city_name, pipeline_generation):
        if "luminosity_score" in data:
            continue
        base = HIGHWAY_LUMINOSITY.get(primary_highway(data), DEFAULT_HIGHWAY_LUMINOSITY)
        data["luminosity_score"] = float(base + np.random.uniform(-5, 5))


def _has_numeric(data: dict, key: str) -> bool:
    if key not in data:
        return False
    try:
        float(data[key])
        return True
    except Exception:
        return False


def _inject_crime_density(G, city_name: str, bbox: dict | None,
                          pipeline_generation: int | None = None):
    """Crime density from the zone model, for edges that do not have one yet."""
    from ingestion.fetch_crime_real import zone_crime_density

    zones = _load_crime_zones(city_name)
    city_index = _load_crime_index().get(city_name, 0.35)

    for u, v, data in _edges_with_checks(G, city_name, pipeline_generation):
        if _has_numeric(data, "crime_density"):
            continue
        try:
            mid_lat, mid_lon = _midpoint(G, u, v)
        except Exception:
            data["crime_density"] = city_index
            data["night_crime_density"] = min(0.95, city_index * 1.35)
            continue

        density = zone_crime_density(mid_lat, mid_lon, zones, floor=city_index * 0.3)
        crime = float(np.clip(density + np.random.normal(0, 0.02), 0.05, 0.95))
        data["crime_density"] = round(crime, 3)
        data["night_crime_density"] = round(min(0.95, crime * 1.35), 3)


def _feature_store_scores(model, store_path: Path) -> dict:
    """(u, v, key) -> predicted safety score for every row of a feature store."""
    # Only the edge ids and model inputs are needed; skipping the other columns
    # keeps memory low for large cities.
    wanted = {"u", "v", "key", *FEATURE_COLS}
    store = pd.read_csv(store_path, usecols=lambda column: column in wanted)
    if store.empty:
        return {}

    keys = list(zip(store["u"].astype("int64").astype(str),
                    store["v"].astype("int64").astype(str),
                    store["key"].astype("int64").astype(str)))
    features = pd.DataFrame(
        {col: (store[col].astype(float) if col in store.columns else 0.0) for col in FEATURE_COLS},
        index=store.index,
    )
    # A repeated edge key keeps its last row, as a dict update would.
    features.index = keys
    features = features[~features.index.duplicated(keep="last")].fillna(0)

    predictions = model.predict(features[FEATURE_COLS])
    return {k: float(np.clip(p, 0, 100)) for k, p in zip(features.index, predictions)}


def _inject_safety_scores(G, city_name: str, pipeline_generation: int | None = None):
    """ML safety score per edge; falls back to the PSI proxy without model or store."""
    _assert_pipeline_active(city_name, pipeline_generation)

    india_model = ARTIFACTS / "india_safety_model.pkl"
    bengaluru_model = ARTIFACTS / "safety_model.pkl"
    model_path = india_model if india_model.exists() else bengaluru_model
    store_path = FEATURE_DIR / f"{city_slug(city_name)}_feature_store.csv"

    if model_path.exists():
        import joblib

        model = joblib.load(model_path)
        log.info("  Scoring with %s", model_path.name)
        if store_path.exists():
            scores = _feature_store_scores(model, store_path)
            if scores:
                for u, v, k, data in _edges_with_checks(G, city_name, pipeline_generation, keys=True):
                    score = scores.get((str(u), str(v), str(k)), FALLBACK_SAFETY)
                    data["safety_score"] = round(score, 2)
                log.info("  ML scores added for %s", city_name)
                return

    log.info("  Using the PSI proxy for %s", city_name)
    _inject_psi_proxy(G)


def _inject_psi_proxy(G):
    """Safety estimate from road class, luminosity and crime only."""
    for u, v, data in G.edges(data=True):
        road = HIGHWAY_ENCODING.get(primary_highway(data), DEFAULT_HIGHWAY_ENCODING)
        lum = to_float(data.get("luminosity_score", 35), 35) / 100
        crime = to_float(data.get("crime_density", 0.3), 0.3)
        psi = float(np.clip(
            28 * lum + 22 * road + 18 * road + 15 * (1 - crime) - 17 * crime
            + np.random.normal(0, 2),
            5.0, 95.0,
        ))
        data["safety_score"] = round(psi, 2)


# Time-of-day weighting ---------------------------------------------------------------

@dataclass(frozen=True)
class PeriodProfile:
    crime_multiplier: float    # scales the crime penalty
    darkness_scale: float      # points lost per unit of darkness beyond the threshold
    closure_penalty: float     # points lost per unit of missing commercial activity


PERIOD_PROFILES = {
    "day":        PeriodProfile(1.0,  0.0,  0.0),
    "evening":    PeriodProfile(1.8,  5.0,  3.0),
    "night":      PeriodProfile(3.5, 18.0, 12.0),
    "late_night": PeriodProfile(6.0, 30.0, 20.0),
}
DARKNESS_THRESHOLD = 0.35     # darkness (1 - lum/100) tolerated before penalising
ACTIVE_COMMERCE = 0.6         # commercial score below which closures are penalised


def period_for_hour(hour: int) -> str:
    """Routing period: day 06-17, evening 17-20, night 20-24, late night 00-06."""
    if 6 <= hour < 17:
        return "day"
    if 17 <= hour < 20:
        return "evening"
    if 20 <= hour < 24:
        return "night"
    return "late_night"


def temporal_safety(base: float, luminosity: float, crime: float,
                    commercial: float, profile: PeriodProfile) -> float:
    """Static safety score adjusted for the period, clamped to [1, 100]."""
    lum_norm = float(np.clip(luminosity / 100, 0, 1))
    crime_pen = float((crime ** 0.5) * 15 * profile.crime_multiplier)
    dark_pen = float(max(0.0, (1.0 - lum_norm) - DARKNESS_THRESHOLD) * profile.darkness_scale)
    comm_pen = float(max(0.0, ACTIVE_COMMERCE - commercial) * profile.closure_penalty)
    return float(np.clip(base - crime_pen - dark_pen - comm_pen, 1.0, 100.0))


def apply_edge_weights(G, alpha: float = 0.7, hour: int = 22, speed_mult: float = 1.0,
                       blocked_hw: set = None, preferred_hw: set = None):
    """Writes temporal_safety, travel_time_mode and composite_weight on every edge.

    composite_weight = alpha * relative risk exposure + (1 - alpha) * relative time
    (see edge_weights). speed_mult scales travel time for the mode (1.0 car, 0.35
    cycling, 0.12 walking); preferred road types get a 15 % safety bonus and blocked
    types a prohibitive weight.
    """
    blocked_hw = blocked_hw or set()
    preferred_hw = preferred_hw or set()
    profile = PERIOD_PROFILES[period_for_hour(hour)]
    scales = cost_scales(G)

    for _, _, data in G.edges(data=True):
        data["temporal_safety"], data["travel_time_mode"], data["composite_weight"] = edge_weights(
            data, profile, alpha, speed_mult, scales, blocked_hw, preferred_hw,
        )
    return G


@dataclass(frozen=True)
class CostScales:
    """City-wide edge averages that put the safety and time terms on one scale."""
    length: float    # metres
    time: float      # seconds of car travel
    risk: float      # 100 / static safety score


def cost_scales(G) -> CostScales:
    """Averages over all edges; cached on the graph since they use static attributes."""
    if "cost_scales" not in G.graph:
        lengths, times, risks = [], [], []
        for _, _, d in G.edges(data=True):
            lengths.append(to_float(d.get("length", 50), 50))
            times.append(to_float(d.get("travel_time", 60), 60))
            risks.append(100.0 / max(min(max(to_float(d.get("safety_score", 40), 40), 0), 100), 1.0))
        G.graph["cost_scales"] = CostScales(
            length=max(float(np.mean(lengths)), 1.0) if lengths else 50.0,
            time=max(float(np.mean(times)), 1.0) if times else 60.0,
            risk=float(np.mean(risks)) if risks else 2.5,
        )
    return G.graph["cost_scales"]


def edge_weights(data: dict, profile: PeriodProfile, alpha: float, speed_mult: float,
                 scales: CostScales, blocked_hw: set, preferred_hw: set) -> tuple:
    """(temporal_safety, travel_time_mode, composite_weight) for one edge.

    The safety term is risk exposure: length times 100 / safety, so a long risky
    stretch costs more than a short one. The time term is car travel time; the
    mode's speed scales every edge alike, so it does not change the ranking.
    Each term is divided by its city-wide average, so an average edge scores
    about 1 on both and alpha is the share of the cost given to safety.
    """
    highway = primary_highway(data)
    base = float(np.clip(to_float(data.get("safety_score", 40), 40), 0, 100))
    if highway in preferred_hw:
        base = min(100, base * 1.15)

    travel_time = to_float(data.get("travel_time", 60), 60)
    if highway in blocked_hw:
        return 1.0, travel_time * speed_mult, BLOCKED_WEIGHT

    safety = temporal_safety(
        base,
        to_float(data.get("luminosity_score", 35), 35),
        to_float(data.get("crime_density", 0.15), 0.15),
        to_float(data.get("commercial_score", 0.3), 0.3),
        profile,
    )
    length = to_float(data.get("length", 50), 50)
    exposure = length / scales.length * (100.0 / max(safety, 1.0)) / scales.risk
    composite = alpha * exposure + (1 - alpha) * travel_time / scales.time
    return round(safety, 2), round(travel_time / max(speed_mult, 0.01), 2), composite


# Route search -------------------------------------------------------------------------

@dataclass(frozen=True)
class ModeProfile:
    speed_mult: float
    blocked: tuple
    preferred: tuple
    min_alpha: float | None = None     # alpha is raised to at least this
    fixed_alpha: float | None = None   # alpha is replaced by this

    def alpha_for(self, requested: float) -> float:
        if self.fixed_alpha is not None:
            return self.fixed_alpha
        if self.min_alpha is not None:
            return max(requested, self.min_alpha)
        return requested


MODE_PROFILES = {
    "car": ModeProfile(
        speed_mult=1.0, blocked=(),
        preferred=("primary", "secondary", "trunk", "motorway"),
    ),
    "motorcycle": ModeProfile(
        speed_mult=0.9, blocked=(),
        preferred=("primary", "secondary", "tertiary"),
        min_alpha=0.75,
    ),
    "walking": ModeProfile(   # about 5 km/h against a 40 km/h car
        speed_mult=0.12,
        blocked=("motorway", "trunk", "motorway_link", "trunk_link"),
        preferred=("footway", "path", "pedestrian", "residential", "living_street"),
        fixed_alpha=0.90,
    ),
    "cycling": ModeProfile(   # about 15 km/h
        speed_mult=0.35,
        blocked=("motorway", "trunk", "motorway_link"),
        preferred=("cycleway", "residential", "tertiary", "living_street"),
        fixed_alpha=0.85,
    ),
}


def _route_stats(G, nodes, hour, speed_mult=1.0):
    """Per-segment details and totals for a node path (empty dict for < 2 nodes)."""
    if not nodes or len(nodes) < 2:
        return {}

    coords = [[to_float(G.nodes[n].get("y", 0), 0), to_float(G.nodes[n].get("x", 0), 0)]
              for n in nodes]
    segments, scores, times, lengths = [], [], [], []

    for u, v in zip(nodes, nodes[1:]):
        edge = G[u][v][0]
        score = to_float(edge.get("temporal_safety", edge.get("safety_score", 40)), 40)
        seconds = to_float(edge.get("travel_time_mode", edge.get("travel_time", 60)), 60)
        metres = to_float(edge.get("length", 50), 50)

        scores.append(score)
        times.append(seconds)
        lengths.append(metres)
        segments.append({
            "u": u,
            "v": v,
            "safety_score": round(score, 1),
            "travel_time_s": round(seconds, 1),
            "length_m": round(metres, 1),
            "highway": primary_highway(edge, default="unknown"),
            "name": str(edge.get("name", "") or ""),
            "safety_grade": score_to_grade(score),
            "safety_color": score_to_color(score),
        })

    # Averaged per metre, so a short stretch at a junction counts for little.
    total_m = sum(lengths)
    average = float(np.average(scores, weights=lengths)) if total_m > 0 else float(np.mean(scores))
    risky_m = sum(m for s, m in zip(scores, lengths) if s < HIGH_RISK_BELOW)
    return {
        "coords": coords,
        "segments": segments,
        "avg_safety_score": round(average, 1),
        "min_safety_score": round(float(np.min(scores)), 1),
        "total_time_min": round(sum(times) / 60, 1),
        "total_dist_km": round(total_m / 1000, 2),
        "risky_km": round(risky_m / 1000, 2),
        "risky_share_pct": round(100 * risky_m / total_m, 1) if total_m > 0 else 0.0,
        "n_segments": len(segments),
        "dangerous_count": sum(1 for s in scores if s < DANGEROUS_BELOW),
        "hour": hour,
        "safety_grade": score_to_grade(average),
    }


def _shortest(G_mode, G_full, origin, destination, weight):
    """Path on the mode graph, retrying on the full graph if it has no path."""
    try:
        return nx.shortest_path(G_mode, origin, destination, weight=weight)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        try:
            return nx.shortest_path(G_full, origin, destination, weight=weight)
        except Exception:
            return None


def _filter_graph_for_mode(G, blocked_hw: set, preferred_hw: set) -> nx.MultiDiGraph:
    """Copy of G without the blocked road types (used for walking and cycling)."""
    keep = [(u, v, k) for u, v, k, data in G.edges(data=True, keys=True)
            if primary_highway(data) not in blocked_hw]
    return G.edge_subgraph(keep).copy()


def route_in_city(city_name: str, origin_lat: float, origin_lon: float,
                  dest_lat: float, dest_lon: float, alpha: float = 0.7, hour: int = 22,
                  mode: str = "car", pipeline_generation: int | None = None) -> dict:
    """Safe and fast routes between two points, with a comparison.

    Returns {"error": ...} when a point cannot be snapped or no path exists.
    """
    log.info("Routing in %s: %.4f,%.4f -> %.4f,%.4f | alpha=%s hour=%s mode=%s",
             city_name, origin_lat, origin_lon, dest_lat, dest_lon, alpha, hour, mode)

    G = load_city_graph(city_name, pipeline_generation=pipeline_generation)

    profile = MODE_PROFILES.get(mode, MODE_PROFILES["car"])
    mode_alpha = profile.alpha_for(alpha)
    blocked, preferred = set(profile.blocked), set(profile.preferred)

    G = apply_edge_weights(G, alpha=mode_alpha, hour=hour, speed_mult=profile.speed_mult,
                           blocked_hw=blocked, preferred_hw=preferred)

    try:
        origin = ox.nearest_nodes(G, origin_lon, origin_lat)
        destination = ox.nearest_nodes(G, dest_lon, dest_lat)
    except Exception as exc:
        return {"error": f"Could not snap to road: {exc}"}

    G_mode = _filter_graph_for_mode(G, blocked, preferred) if blocked else G

    safe_nodes = _shortest(G_mode, G, origin, destination, "composite_weight")
    if safe_nodes is None:
        return {"error": f"No safe route found in {city_name}"}
    fast_nodes = _shortest(G_mode, G, origin, destination, "travel_time")
    if fast_nodes is None:
        return {"error": f"No fast route found in {city_name}"}

    return compare_routes(G, city_name, mode, mode_alpha, hour, profile.speed_mult,
                          (origin_lat, origin_lon), (dest_lat, dest_lon), safe_nodes, fast_nodes)


def compare_routes(G, city_name: str, mode: str, mode_alpha: float, hour: int, speed_mult: float,
                   origin: tuple, destination: tuple, safe_nodes: list, fast_nodes: list) -> dict:
    """route_in_city result for two node paths on a weighted graph.

    origin and destination are the requested (lat, lon) points.
    """
    origin_lat, origin_lon = origin
    dest_lat, dest_lon = destination
    safe = _route_stats(G, safe_nodes, hour, speed_mult)
    fast = _route_stats(G, fast_nodes, hour, speed_mult)
    if not safe or not fast:
        return {"error": "Route computation returned empty result."}

    extra_minutes = safe["total_time_min"] - fast["total_time_min"]
    safety_gain = safe["avg_safety_score"] - fast["avg_safety_score"]
    log.info("  [%s] safe %.1f pts / %.1f min | fast %.1f pts / %.1f min | gain %+.1f for %+.1f min",
             mode, safe["avg_safety_score"], safe["total_time_min"],
             fast["avg_safety_score"], fast["total_time_min"], safety_gain, extra_minutes)

    return {
        "safe_route": safe,
        "fast_route": fast,
        "comparison": {
            "time_penalty_min": round(extra_minutes, 1),
            "safety_gain_points": round(safety_gain, 1),
            "risky_km_avoided": round(fast["risky_km"] - safe["risky_km"], 2),
            "high_risk_below": HIGH_RISK_BELOW,
            "recommendation": (
                "Take the safer route — minimal time cost."
                if extra_minutes <= WORTH_IT_MINUTES else
                "Safer route adds significant time. Your choice."
            ),
            "safer_route_worth_it": extra_minutes <= WORTH_IT_MINUTES or safety_gain >= WORTH_IT_POINTS,
        },
        "city": city_name,
        "mode": mode,
        "alpha": mode_alpha,
        "hour": hour,
        "origin": {"lat": origin_lat, "lon": origin_lon},
        "destination": {"lat": dest_lat, "lon": dest_lon},
    }


# City lookup ----------------------------------------------------------------------------

def get_available_cities() -> list:
    """Names of cities with a graph file, alphabetically."""
    return sorted(p.stem.replace("_", " ").title() for p in CITY_GRAPHS.glob("*.graphml"))


def detect_city(lat: float, lon: float) -> str:
    """City for a GPS position (bbox containment, then nearest centre)."""
    try:
        from ingestion.fetch_india_graph import find_city_for_coordinates
        return find_city_for_coordinates(lat, lon)
    except Exception as exc:
        log.error("City detection failed: %s", exc)
        return "Bengaluru"
