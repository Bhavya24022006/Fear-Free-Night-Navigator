"""
Single-city (Bengaluru) routing, kept from the first version of the project.

It still backs GET /score. The edge weighting is the same time-aware formula
as the multi-city router:

    composite_weight = alpha * 100 / temporal_safety + (1 - alpha) * normalised time

Check it with:
    python -m routing.dijkstra

Needs data/processed/bengaluru_scored_graph.graphml (or data/raw/bengaluru_graph.graphml).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

from ai.ml.features import primary_highway, to_float
from ai.ml.predict import score_to_color, score_to_grade

log = logging.getLogger("routing.dijkstra")

DATA_PROCESSED = Path("data/processed")
ARTIFACTS = Path("ai/ml/artifacts")

DEFAULT_ALPHA = 0.7
MIN_SAFETY_SCORE = 1.0
DEFAULT_HOUR = 22
DANGEROUS_BELOW = 30


@lru_cache(maxsize=1)
def load_graph():
    """The scored Bengaluru graph if present, else the raw one (cached)."""
    for path in (DATA_PROCESSED / "bengaluru_scored_graph.graphml",
                 Path("data/raw/bengaluru_graph.graphml")):
        if path.exists():
            log.info("Loading graph %s", path)
            G = ox.load_graphml(path)
            log.info("Graph ready: %s nodes, %s edges", f"{len(G.nodes):,}", f"{len(G.edges):,}")
            return G
    raise FileNotFoundError("No graph found. Run the ingestion scripts first.")


def inject_ml_scores(G, hour: int = 22):
    """Copies safety_score_ml from the Bengaluru ML feature store onto the edges."""
    ml_path = DATA_PROCESSED / "bengaluru_feature_store_ml.csv"
    if not ml_path.exists():
        log.warning("ML scores not found; every edge gets 40.")
        for _, _, _, data in G.edges(data=True, keys=True):
            data["safety_score"] = 40.0
        return G

    log.info("Adding ML safety scores to the graph ...")
    df = pd.read_csv(ml_path)
    scores = (df["safety_score_ml"] if "safety_score_ml" in df.columns
              else pd.Series(40.0, index=df.index))
    lookup = {
        (u, v, k): to_float(s, 40.0)
        for u, v, k, s in zip(df["u"].astype(str), df["v"].astype(str),
                              df["key"].astype(str), scores)
    }

    matched = 0
    for u, v, k, data in G.edges(data=True, keys=True):
        score = lookup.get((str(u), str(v), str(k)))
        data["safety_score"] = 40.0 if score is None else score
        matched += score is not None
    log.info("Scores matched for %s edges, defaulted for %s",
             f"{matched:,}", f"{len(G.edges) - matched:,}")
    return G


def compute_edge_weights(G, alpha: float = DEFAULT_ALPHA, hour: int = DEFAULT_HOUR):
    """Time-aware composite weights (car settings of the multi-city router)."""
    from routing.city_router import apply_edge_weights

    return apply_edge_weights(G, alpha=alpha, hour=hour)


def find_nearest_node(G, lat: float, lon: float) -> int:
    return ox.nearest_nodes(G, lon, lat)


def compute_route(G, orig_node: int, dest_node: int,
                  weight: str = "composite_weight") -> Optional[list]:
    """Node path minimising `weight`, or None when there is no path."""
    try:
        return nx.shortest_path(G, orig_node, dest_node, weight=weight)
    except nx.NetworkXNoPath:
        log.warning("No path between %s and %s", orig_node, dest_node)
    except Exception as exc:
        log.error("Routing error: %s", exc)
    return None


def compute_route_stats(G, route: list, hour: int = 22) -> dict:
    """Segments and totals for a node path (empty dict for fewer than two nodes)."""
    if not route or len(route) < 2:
        return {}

    coords = [[to_float(G.nodes[n]["y"], 12.97), to_float(G.nodes[n]["x"], 77.59)] for n in route]
    segments, scores, times, lengths = [], [], [], []

    for u, v in zip(route, route[1:]):
        edge = G[u][v][0]
        score = to_float(edge.get("temporal_safety", edge.get("safety_score", 40.0)), 40.0)
        seconds = to_float(edge.get("travel_time", 60.0), 60.0)
        metres = to_float(edge.get("length", 50.0), 50.0)

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

    average = float(np.mean(scores))
    return {
        "coords": coords,
        "segments": segments,
        "avg_safety_score": round(average, 1),
        "min_safety_score": round(float(np.min(scores)), 1),
        "total_time_min": round(sum(times) / 60, 1),
        "total_dist_km": round(sum(lengths) / 1000, 2),
        "n_segments": len(segments),
        "dangerous_count": sum(1 for s in segments if s["safety_score"] < DANGEROUS_BELOW),
        "hour": hour,
        "safety_grade": score_to_grade(average),
    }


def get_dual_routes(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float,
                    alpha: float = DEFAULT_ALPHA, hour: int = DEFAULT_HOUR) -> dict:
    """Safe and fast Bengaluru routes with a comparison."""
    G = load_graph()
    if "safety_score" not in next(iter(G.edges(data=True)))[2]:
        G = inject_ml_scores(G, hour)
    G = compute_edge_weights(G, alpha=alpha, hour=hour)

    orig_node = find_nearest_node(G, origin_lat, origin_lon)
    dest_node = find_nearest_node(G, dest_lat, dest_lon)
    log.info("Routing %.4f,%.4f -> %.4f,%.4f | alpha=%s hour=%s",
             origin_lat, origin_lon, dest_lat, dest_lon, alpha, hour)

    safe_nodes = compute_route(G, orig_node, dest_node, "composite_weight")
    fast_nodes = compute_route(G, orig_node, dest_node, "travel_time")
    if safe_nodes is None or fast_nodes is None:
        return {"error": "No route found between these points."}

    safe = compute_route_stats(G, safe_nodes, hour)
    fast = compute_route_stats(G, fast_nodes, hour)
    extra_minutes = safe["total_time_min"] - fast["total_time_min"]
    gain = safe["avg_safety_score"] - fast["avg_safety_score"]
    log.info("Safe %.1f pts / %.1f min | fast %.1f pts / %.1f min | gain %+.1f for %+.1f min",
             safe["avg_safety_score"], safe["total_time_min"],
             fast["avg_safety_score"], fast["total_time_min"], gain, extra_minutes)

    return {
        "safe_route": safe,
        "fast_route": fast,
        "comparison": {
            "time_penalty_min": round(extra_minutes, 1),
            "safety_gain_points": round(gain, 1),
            "recommendation": (
                "Take the safer route — minimal time cost."
                if extra_minutes <= 5 else
                "Safer route adds significant time. Your choice."
            ),
            "safer_route_worth_it": extra_minutes <= 5 or gain >= 15,
        },
        "alpha": alpha,
        "hour": hour,
        "origin": {"lat": origin_lat, "lon": origin_lon},
        "destination": {"lat": dest_lat, "lon": dest_lon},
    }


def run_test():
    logging.basicConfig(level=logging.INFO)
    trips = [
        ("MG Road to Koramangala", 12.9767, 77.6009, 12.9352, 77.6245),
        ("Majestic to Indiranagar", 12.9767, 77.5713, 12.9718, 77.6412),
        ("Shivajinagar to Jayanagar", 12.9839, 77.5929, 12.9220, 77.5833),
    ]
    for label, o_lat, o_lon, d_lat, d_lon in trips:
        print(f"\n{label}")
        for hour in (9, 22, 0):
            result = get_dual_routes(o_lat, o_lon, d_lat, d_lon, alpha=0.7, hour=hour)
            if "error" in result:
                print(f"  {hour:02d}:00  error: {result['error']}")
                continue
            print(f"  {hour:02d}:00  safe {result['safe_route']['avg_safety_score']:.1f} | "
                  f"fast {result['fast_route']['avg_safety_score']:.1f} | "
                  f"gain {result['comparison']['safety_gain_points']:+.1f} | "
                  f"extra {result['comparison']['time_penalty_min']:+.1f} min")


if __name__ == "__main__":
    run_test()
