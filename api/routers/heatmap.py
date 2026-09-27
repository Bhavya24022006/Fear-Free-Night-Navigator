"""GET /heatmap - sampled edge safety scores for drawing a city overlay."""

import asyncio
import logging
import random

from fastapi import APIRouter, HTTPException, Query

from ai.ml.features import to_float
from api.models.response import HeatmapResponse

log = logging.getLogger("api.heatmap")
router = APIRouter(prefix="/heatmap", tags=["heatmap"])

SAMPLE_SEED = 42


def _edge_points(G) -> list:
    """[lat, lon, score] at every edge midpoint.

    Uses the time-adjusted score from the latest routing request when present,
    otherwise the static safety score.
    """
    points = []
    for u, v, data in G.edges(data=True):
        try:
            mid_lat = (float(G.nodes[u]["y"]) + float(G.nodes[v]["y"])) / 2
            mid_lon = (float(G.nodes[u]["x"]) + float(G.nodes[v]["x"])) / 2
        except (KeyError, ValueError):
            continue
        score = to_float(data.get("temporal_safety", data.get("safety_score", 40.0)), 40.0)
        points.append([round(mid_lat, 6), round(mid_lon, 6), round(score, 1)])
    return points


def sample_edge_points(G, sample_n: int) -> list:
    """Up to sample_n edge points; the same sample for the same graph."""
    points = _edge_points(G)
    if len(points) > sample_n:
        random.seed(SAMPLE_SEED)
        points = random.sample(points, sample_n)
    return points


@router.get("/", response_model=HeatmapResponse)
async def get_heatmap(
    sample_n: int = Query(3000, ge=100, le=10000),
    city: str = Query("Bengaluru"),
):
    log.info("Heatmap request for %s (%d points)", city, sample_n)
    from routing.city_router import (
        CityPipelineCancelled,
        begin_latest_city_pipeline,
        load_city_graph,
    )
    from routing.demo_cache import find_heatmap

    try:
        generation = begin_latest_city_pipeline(city)
        points = find_heatmap(city, sample_n)
        if points is None:
            G = await asyncio.to_thread(load_city_graph, city, generation)
            points = sample_edge_points(G, sample_n)

        log.info("Heatmap for %s: %d points", city, len(points))
        return HeatmapResponse(points=points, count=len(points))

    except CityPipelineCancelled as exc:
        log.info("Heatmap request replaced by a newer city selection: %s", exc)
        raise HTTPException(
            status_code=409,
            detail="City changed while processing heatmap. Please retry with the latest city selection.",
        )
    except Exception as exc:
        log.error("Heatmap error: %s", exc)
        return HeatmapResponse(points=[], count=0)
