"""GET /score - safety score of the road nearest to a point (Bengaluru graph)."""

import logging

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from ai.ml.predict import score_to_color, score_to_grade, score_to_label
from api.models.response import ScoreResponse

log = logging.getLogger("api.score")
router = APIRouter(prefix="/score", tags=["scoring"])


@router.get("/", response_model=ScoreResponse)
async def get_score(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    hour: int = Query(22, ge=0, le=23),
):
    """Average safety score of the edges leaving the nearest graph node."""
    try:
        from routing.dijkstra import find_nearest_node, load_graph

        G = load_graph()
        node = find_nearest_node(G, lat, lon)
        edges = list(G.edges(node, data=True))
        if not edges:
            raise HTTPException(status_code=404, detail="No road found nearby.")

        score = float(np.mean([float(data.get("safety_score", 40.0)) for _, _, data in edges]))
        return ScoreResponse(
            lat=lat,
            lon=lon,
            safety_score=round(score, 1),
            safety_grade=score_to_grade(score),
            safety_label=score_to_label(score),
            safety_color=score_to_color(score),
            hour=hour,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Score error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
