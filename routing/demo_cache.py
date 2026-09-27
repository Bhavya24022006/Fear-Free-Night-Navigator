"""
Pre-computed routes and heatmap for recording a demo.

A live route request re-weights every edge of the city graph in Python, which
takes minutes for a large city. For trips between the frontend's place buttons
this module computes every answer once, in bulk:

    python -m routing.demo_cache --city Bengaluru

It covers every ordered pair of place buttons (frontend/src/constants.js),
every travel mode, every time period and every value the safety slider can
send, and writes one JSON file per request to data/demo_cache/<city>/, plus the
heatmap overlay. The API answers those requests from the files without loading
the road graph; any other request is routed live as before.

The hour only affects a route through its period (day, evening, night, late
night), so four periods cover all 24 hours. Edge weights are computed with
numpy and paths with scipy's Dijkstra; the per-segment figures in each result
come from the same functions the live router uses, and the numpy weights are
checked against city_router.edge_weights on a sample of edges.

manifest.json records a content signature of the graph, feature store, model,
crime and night-light files and of city_router.py. When any of them changes,
the stored files are ignored until the cache is rebuilt. Signatures survive
copying and git checkouts, and a file that is missing is not checked, so a
copy of the repository without the data folder can still serve the demo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from datetime import datetime
from functools import partial
from pathlib import Path

import numpy as np
import osmnx as ox
import pandas as pd
from scipy.sparse import csr_array
from scipy.sparse.csgraph import dijkstra

from ai.ml.features import city_slug, primary_highway, to_float
from routing import city_router as cr

log = logging.getLogger("routing.demo_cache")

CACHE_ROOT = Path("data/demo_cache")
CONSTANTS_JS = Path("frontend/src/constants.js")
HEATMAP_SAMPLE_N = 3000                        # HEATMAP_POINTS in constants.js
SLIDER_ALPHAS = [i / 10 for i in range(11)]    # AlphaSlider: 0 to 1 in steps of 0.1
CHECK_SAMPLE = 500                             # edges compared with edge_weights per setting
MIN_WEIGHT = 1e-9                              # keeps zero-cost edges in scipy's graph
SAMPLE_BYTES = 1 << 20                         # large files are signed by size, first and last MiB

_stale_warned: set[str] = set()


# Lookup (used by the API) ----------------------------------------------------------------

def _source_files(city_name: str) -> dict[str, Path]:
    """Files whose change makes the stored routes outdated, by a name that is the same on every machine."""
    slug = city_slug(city_name)
    paths = [
        cr.CITY_GRAPHS / f"{slug}.graphml",
        cr.DATA_PROC / f"{slug}_scored_graph.graphml",
        cr.FEATURE_DIR / f"{slug}_feature_store.csv",
        cr.ARTIFACTS / "india_safety_model.pkl",
        cr.ARTIFACTS / "safety_model.pkl",
        cr.DATA_RAW / "city_crime_index.json",
        cr.DATA_RAW / "city_crime_zones.json",
        cr.VIIRS_DIR / f"{slug}.npy",
    ]
    sources = {path.as_posix(): path for path in paths}
    sources["routing/city_router.py"] = Path(cr.__file__)
    return sources


def _signature(path: Path) -> str | None:
    """Hash of a file's content, ignoring line endings (None when it is missing).

    Large files are signed by their size and first and last MiB, which is quick
    and still changes whenever the data is rebuilt.
    """
    if not path.exists():
        return None
    size = path.stat().st_size
    with open(path, "rb") as fh:
        if size <= 2 * SAMPLE_BYTES:
            content = fh.read()
        else:
            content = fh.read(SAMPLE_BYTES)
            fh.seek(-SAMPLE_BYTES, 2)
            content += fh.read() + str(size).encode()
    return hashlib.sha1(content.replace(b"\r\n", b"\n")).hexdigest()


def source_signatures(city_name: str) -> dict:
    return {name: _signature(path) for name, path in _source_files(city_name).items()}


def _cache_dir(city_name: str) -> Path:
    return CACHE_ROOT / city_slug(city_name)


def _current_dir(city_name: str) -> Path | None:
    """The city's cache folder if it was built from the files present here, else None."""
    folder = _cache_dir(city_name)
    try:
        stored = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["sources"]
    except (OSError, ValueError, KeyError):
        return None
    changed = [name for name, signature in source_signatures(city_name).items()
               if signature is not None and signature != stored.get(name)]
    if not changed:
        return folder
    if city_name not in _stale_warned:
        _stale_warned.add(city_name)
        log.warning("Demo cache for %s is out of date (%s changed). "
                    "Rebuild it with: python -m routing.demo_cache --city %s",
                    city_name, ", ".join(changed), city_name)
    return None


def available_cities() -> list:
    """Cities with a road graph or a demo cache, alphabetically."""
    cached = set()
    for manifest in CACHE_ROOT.glob("*/manifest.json"):
        try:
            cached.add(json.loads(manifest.read_text(encoding="utf-8"))["city"])
        except (OSError, ValueError, KeyError):
            continue
    return sorted(set(cr.get_available_cities()) | cached)


def _route_file(origin: tuple, destination: tuple, mode: str, period: str, alpha: float) -> str:
    (o_lat, o_lon), (d_lat, d_lon) = origin, destination
    return f"route_{o_lat:.5f}_{o_lon:.5f}_{d_lat:.5f}_{d_lon:.5f}_{mode}_{period}_{alpha:.2f}.json"


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def find_route(city_name: str, origin_lat: float, origin_lon: float, dest_lat: float,
               dest_lon: float, alpha: float, hour: int, mode: str) -> dict | None:
    """Stored route_in_city result for this request, or None when there is none."""
    folder = _current_dir(city_name)
    if folder is None:
        return None
    profile = cr.MODE_PROFILES.get(mode, cr.MODE_PROFILES["car"])
    name = _route_file((origin_lat, origin_lon), (dest_lat, dest_lon), mode,
                       cr.period_for_hour(hour), profile.alpha_for(alpha))
    result = _read(folder / name)
    if result is None:
        return None

    log.info("Answered from the demo cache: %s", name)
    if "error" not in result:
        # Stored for one hour of the period; report the hour and points requested.
        result["hour"] = result["safe_route"]["hour"] = result["fast_route"]["hour"] = hour
        result["origin"] = {"lat": origin_lat, "lon": origin_lon}
        result["destination"] = {"lat": dest_lat, "lon": dest_lon}
    return result


def find_heatmap(city_name: str, sample_n: int) -> list | None:
    """Stored heatmap points for a city, or None when there are none."""
    folder = _current_dir(city_name)
    if folder is None:
        return None
    points = _read(folder / f"heatmap_{sample_n}.json")
    if points is not None:
        log.info("Heatmap for %s answered from the demo cache", city_name)
    return points


# Building --------------------------------------------------------------------------------

def _frontend_places(city_name: str) -> list[dict]:
    """Place buttons the frontend offers for a city (landmarksFor in constants.js)."""
    text = CONSTANTS_JS.read_text(encoding="utf-8")
    city = re.escape(city_name)
    landmarks = re.search(r"export const LANDMARKS = \{(.*?)\n\};", text, re.S)
    block = landmarks and re.search(rf"^\s*{city}: \[(.*?)\],", landmarks.group(1), re.S | re.M)
    if block:
        entries = re.findall(r'name: "([^"]+)", lat: ([-\d.]+), lon: ([-\d.]+)', block.group(1))
        return [{"name": name, "lat": float(lat), "lon": float(lon)} for name, lat, lon in entries]
    centre = re.search(rf"^\s*{city}: \[([-\d.]+), ([-\d.]+)\],", text, re.M)
    if centre:
        return [{"name": "City centre", "lat": float(centre.group(1)), "lon": float(centre.group(2))}]
    return []


def _period_hours() -> dict:
    """One hour for each routing period, e.g. {"late_night": 0, "day": 6, ...}."""
    hours = {}
    for hour in range(24):
        hours.setdefault(cr.period_for_hour(hour), hour)
    return hours


def _walk_back(predecessors: np.ndarray, source: int, target: int) -> list | None:
    if source == target:
        return [source]
    if predecessors[target] < 0:
        return None
    path = [target]
    while path[-1] != source:
        path.append(int(predecessors[path[-1]]))
    return path[::-1]


class _EdgeArrays:
    """Edge attributes of a scored city graph as numpy arrays, for bulk routing."""

    def __init__(self, G):
        self.nodes = list(G.nodes)
        self.index = {node: i for i, node in enumerate(self.nodes)}
        self.scales = cr.cost_scales(G)

        n = G.number_of_edges()
        self.tail = np.empty(n, np.int32)
        self.head = np.empty(n, np.int32)
        safety = np.empty(n)
        self.luminosity = np.empty(n)
        self.crime = np.empty(n)
        self.commercial = np.empty(n)
        self.length = np.empty(n)
        self.travel_time = np.empty(n)     # as edge_weights reads it (missing = 60)
        self.search_time = np.empty(n)     # as networkx reads it for the fast route (missing = 1)
        highways = [None] * n

        sample = set(np.random.default_rng(0).choice(n, size=min(CHECK_SAMPLE, n), replace=False).tolist())
        self.sample = []
        for i, (u, v, data) in enumerate(G.edges(data=True)):
            self.tail[i] = self.index[u]
            self.head[i] = self.index[v]
            safety[i] = to_float(data.get("safety_score", 40), 40)
            self.luminosity[i] = to_float(data.get("luminosity_score", 35), 35)
            self.crime[i] = to_float(data.get("crime_density", 0.15), 0.15)
            self.commercial[i] = to_float(data.get("commercial_score", 0.3), 0.3)
            self.length[i] = to_float(data.get("length", 50), 50)
            self.travel_time[i] = to_float(data.get("travel_time", 60), 60)
            self.search_time[i] = to_float(data.get("travel_time", 1), 1)
            highways[i] = primary_highway(data)
            if i in sample:
                self.sample.append((i, data))

        self.base = np.clip(safety, 0, 100)
        self.highway = pd.Categorical(highways)

    def road_mask(self, road_types) -> np.ndarray:
        return np.asarray(self.highway.isin(list(road_types)))

    def temporal_safety(self, profile: cr.PeriodProfile, preferred: np.ndarray) -> np.ndarray:
        """city_router.temporal_safety for every edge, with the preferred-road bonus."""
        base = np.where(preferred, np.minimum(100, self.base * 1.15), self.base)
        lum_norm = np.clip(self.luminosity / 100, 0, 1)
        crime_pen = (self.crime ** 0.5) * 15 * profile.crime_multiplier
        dark_pen = np.maximum(0.0, (1.0 - lum_norm) - cr.DARKNESS_THRESHOLD) * profile.darkness_scale
        comm_pen = np.maximum(0.0, cr.ACTIVE_COMMERCE - self.commercial) * profile.closure_penalty
        return np.clip(base - crime_pen - dark_pen - comm_pen, 1.0, 100.0)

    def composite(self, safety: np.ndarray, alpha: float, blocked: np.ndarray) -> np.ndarray:
        """composite_weight of apply_edge_weights for every edge."""
        exposure = self.length / self.scales.length * (100.0 / np.maximum(safety, 1.0)) / self.scales.risk
        weights = alpha * exposure + (1 - alpha) * self.travel_time / self.scales.time
        weights[blocked] = cr.BLOCKED_WEIGHT
        return weights

    def check(self, weights: np.ndarray, weigh) -> None:
        """Stops the build if the numpy weights differ from city_router.edge_weights."""
        for i, data in self.sample:
            expected = weigh(data)[2]
            if not np.isclose(weights[i], expected, rtol=1e-9, atol=1e-9):
                raise RuntimeError(f"Edge {i}: numpy weight {weights[i]} but edge_weights gives {expected}")

    def _graph(self, weights: np.ndarray, keep: np.ndarray | None) -> csr_array:
        """Directed graph keeping the cheapest of parallel edges, as networkx does."""
        tail, head = self.tail, self.head
        if keep is not None:
            tail, head, weights = tail[keep], head[keep], weights[keep]
        pair = tail.astype(np.int64) * len(self.nodes) + head
        order = np.lexsort((weights, pair))
        first = np.ones(len(order), bool)
        first[1:] = pair[order][1:] != pair[order][:-1]
        chosen = order[first]
        size = len(self.nodes)
        return csr_array((np.maximum(weights[chosen], MIN_WEIGHT), (tail[chosen], head[chosen])),
                         shape=(size, size))

    def shortest_paths(self, weights: np.ndarray, keep: np.ndarray | None, pairs: set) -> dict:
        """{(origin, destination): node path or None} for node-index pairs.

        Like city_router._shortest: searches the mode's edges (keep) first and
        the whole graph for pairs that have no path there.
        """
        found, todo = {}, sorted(pairs)
        for edges_kept in ((keep, None) if keep is not None else (None,)):
            if not todo:
                break
            sources = sorted({origin for origin, _ in todo})
            _, predecessors = dijkstra(self._graph(weights, edges_kept), directed=True,
                                       indices=sources, return_predecessors=True)
            row = {source: r for r, source in enumerate(sources)}
            missing = []
            for origin, destination in todo:
                path = _walk_back(predecessors[row[origin]], origin, destination)
                if path is None:
                    missing.append((origin, destination))
                else:
                    found[(origin, destination)] = [self.nodes[i] for i in path]
            todo = missing
        found.update({pair: None for pair in todo})
        return found


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def build(city_name: str, sample_n: int = HEATMAP_SAMPLE_N) -> int:
    """Computes and stores every demo request for a city; returns the number of routes."""
    from api.routers.heatmap import sample_edge_points

    places = _frontend_places(city_name)
    if not places:
        raise SystemExit(f"No place buttons for {city_name} in {CONSTANTS_JS}")
    log.info("Places for %s: %s", city_name, ", ".join(p["name"] for p in places))

    started = time.time()
    sources = source_signatures(city_name)
    G = cr.load_city_graph(city_name)
    logging.getLogger("routing.city_router").setLevel(logging.WARNING)   # one line per route otherwise

    folder = _cache_dir(city_name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").unlink(missing_ok=True)   # the cache stays off until the build completes
    for old in folder.glob("*.json"):
        old.unlink()

    # Taken before any route writes time-of-day scores onto edges, like a fresh server.
    _write(folder / f"heatmap_{sample_n}.json", sample_edge_points(G, sample_n))

    log.info("Reading edge attributes ...")
    edges = _EdgeArrays(G)
    snapped = ox.nearest_nodes(G, [p["lon"] for p in places], [p["lat"] for p in places])
    place_nodes = [edges.index[node] for node in snapped]
    trips = [(a, b) for a in range(len(places)) for b in range(len(places))]
    node_pairs = {(place_nodes[a], place_nodes[b]) for a, b in trips}

    written = 0
    for mode, profile in cr.MODE_PROFILES.items():
        blocked_hw, preferred_hw = set(profile.blocked), set(profile.preferred)
        blocked = edges.road_mask(blocked_hw)
        preferred = edges.road_mask(preferred_hw)
        keep = ~blocked if blocked_hw else None
        fast_paths = edges.shortest_paths(edges.search_time, keep, node_pairs)

        for period, hour in _period_hours().items():
            period_profile = cr.PERIOD_PROFILES[period]
            safety = edges.temporal_safety(period_profile, preferred)

            for alpha in sorted({profile.alpha_for(a) for a in SLIDER_ALPHAS}):
                weigh = partial(cr.edge_weights, profile=period_profile, alpha=alpha,
                                speed_mult=profile.speed_mult, scales=edges.scales,
                                blocked_hw=blocked_hw, preferred_hw=preferred_hw)
                weights = edges.composite(safety, alpha, blocked)
                edges.check(weights, weigh)
                safe_paths = edges.shortest_paths(weights, keep, node_pairs)

                for a, b in trips:
                    origin, destination = places[a], places[b]
                    pair = (place_nodes[a], place_nodes[b])
                    safe_nodes, fast_nodes = safe_paths[pair], fast_paths[pair]
                    if safe_nodes is None:
                        result = {"error": f"No safe route found in {city_name}"}
                    elif fast_nodes is None:
                        result = {"error": f"No fast route found in {city_name}"}
                    else:
                        # _route_stats reads these from the first edge between each node pair.
                        for nodes in (safe_nodes, fast_nodes):
                            for u, v in zip(nodes, nodes[1:]):
                                data = G[u][v][0]
                                data["temporal_safety"], data["travel_time_mode"], _ = weigh(data)
                        result = cr.compare_routes(
                            G, city_name, mode, alpha, hour, profile.speed_mult,
                            (origin["lat"], origin["lon"]), (destination["lat"], destination["lon"]),
                            safe_nodes, fast_nodes,
                        )
                    name = _route_file((origin["lat"], origin["lon"]),
                                       (destination["lat"], destination["lon"]), mode, period, alpha)
                    _write(folder / name, result)
                    written += 1

            log.info("  %-10s %-10s done (%d routes, %.0f s)", mode, period, written, time.time() - started)

    _write(folder / "manifest.json", {
        "city": city_name,
        "sources": sources,
        "built": datetime.now().isoformat(timespec="seconds"),
        "places": places,
        "routes": written,
    })
    log.info("Stored %d routes and the heatmap in %s (%.0f s)", written, folder, time.time() - started)
    return written


def main():
    parser = argparse.ArgumentParser(
        description="Pre-compute routes between the frontend's place buttons for a demo.")
    parser.add_argument("--city", default="Bengaluru")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    build(args.city)


if __name__ == "__main__":
    main()
