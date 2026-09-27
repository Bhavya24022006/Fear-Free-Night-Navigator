"""
Loading helpers for the single-city (Bengaluru) graph.

Used at API start-up to warm the legacy graph, and by the GET / info endpoint.
"""

from __future__ import annotations

import logging
import random
from functools import lru_cache
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd

from ai.ml.features import to_float

log = logging.getLogger("routing.graph")

DATA_PROCESSED = Path("data/processed")
DATA_RAW = Path("data/raw")

# Values given to edges that the ML scores file does not cover.
EDGE_DEFAULTS = {"safety_score": 40.0, "crime_density": 0.2, "luminosity_score": 35.0}


@lru_cache(maxsize=1)
def get_graph():
    """Bengaluru graph with safety scores (cached for the process lifetime).

    Prefers the pre-scored GraphML; otherwise loads the raw graph and copies
    scores from bengaluru_feature_store_ml.csv.
    """
    scored = DATA_PROCESSED / "bengaluru_scored_graph.graphml"
    if scored.exists():
        log.info("Loading scored graph %s", scored)
        G = ox.load_graphml(scored)
        log.info("Scored graph: %s nodes, %s edges", f"{len(G.nodes):,}", f"{len(G.edges):,}")
        return G

    raw = DATA_RAW / "bengaluru_graph.graphml"
    if raw.exists():
        log.info("Loading base graph %s", raw)
        G = inject_scores_from_csv(ox.load_graphml(raw))
        log.info("Base graph: %s nodes, %s edges", f"{len(G.nodes):,}", f"{len(G.edges):,}")
        return G

    raise FileNotFoundError("No graph found.\nRun: python -m ingestion.fetch_india_graph")


def inject_scores_from_csv(G) -> nx.MultiDiGraph:
    """Copies safety score, crime density and luminosity from the ML CSV onto edges."""
    ml_path = DATA_PROCESSED / "bengaluru_feature_store_ml.csv"
    if not ml_path.exists():
        log.warning("ML scores CSV not found; every edge gets 40.")
        for _, _, _, data in G.edges(data=True, keys=True):
            data["safety_score"] = 40.0
        return G

    log.info("Adding ML scores from %s ...", ml_path)
    df = pd.read_csv(ml_path)

    def column(name, default):
        return df[name].astype(float) if name in df.columns else pd.Series(default, index=df.index)

    safety = column("safety_score_ml", 40.0)
    crime = column("crime_density", 0.2)
    luminosity = column("luminosity_score", 35.0)
    lookup = {
        (u, v, k): {"safety_score": s, "crime_density": c, "luminosity_score": lum}
        for u, v, k, s, c, lum in zip(df["u"].astype(str), df["v"].astype(str),
                                      df["key"].astype(str), safety, crime, luminosity)
    }

    matched = 0
    for u, v, k, data in G.edges(data=True, keys=True):
        values = lookup.get((str(u), str(v), str(k)))
        data.update(values if values else EDGE_DEFAULTS)
        matched += bool(values)
    log.info("Scores matched for %s edges, defaulted for %s",
             f"{matched:,}", f"{len(G.edges) - matched:,}")
    return G


def get_graph_stats(G) -> dict:
    """Size of the graph and summary of its safety scores and travel times."""
    scores = [to_float(data.get("safety_score", 40.0), 40.0) for _, _, data in G.edges(data=True)]
    times = [to_float(data.get("travel_time", 60.0), 60.0) for _, _, data in G.edges(data=True)]
    return {
        "n_nodes": len(G.nodes),
        "n_edges": len(G.edges),
        "avg_safety_score": round(float(np.mean(scores)), 2),
        "min_safety_score": round(float(np.min(scores)), 2),
        "max_safety_score": round(float(np.max(scores)), 2),
        "avg_travel_time_s": round(float(np.mean(times)), 2),
    }


def get_heatmap_data(G, sample_n: int = 5000) -> list:
    """[lat, lon, safety_score] at edge midpoints, sampled to at most sample_n points."""
    points = []
    for u, v, data in G.edges(data=True):
        mid_lat = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
        mid_lon = (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2
        points.append([round(mid_lat, 6), round(mid_lon, 6),
                       round(float(data.get("safety_score", 40.0)), 1)])

    if len(points) > sample_n:
        random.seed(42)
        points = random.sample(points, sample_n)
    return points


def nearest_node(G, lat: float, lon: float) -> int:
    """Graph node closest to the given coordinates."""
    return ox.nearest_nodes(G, lon, lat)
