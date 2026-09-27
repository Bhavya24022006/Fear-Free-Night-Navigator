"""Response shapes returned by the API."""

from typing import Any, Dict, List

from pydantic import BaseModel


class SegmentResponse(BaseModel):
    u: int
    v: int
    safety_score: float
    travel_time_s: float
    length_m: float
    highway: str
    name: str
    safety_grade: str
    safety_color: str


class RouteStatsResponse(BaseModel):
    coords: List[List[float]]
    avg_safety_score: float
    min_safety_score: float
    total_time_min: float
    total_dist_km: float
    n_segments: int
    dangerous_count: int
    safety_grade: str
    segments: List[Dict[str, Any]]


class ComparisonResponse(BaseModel):
    time_penalty_min: float
    safety_gain_points: float
    recommendation: str
    safer_route_worth_it: bool


class DualRouteResponse(BaseModel):
    safe_route: RouteStatsResponse
    fast_route: RouteStatsResponse
    comparison: ComparisonResponse
    alpha: float
    hour: int
    origin: Dict[str, float]
    destination: Dict[str, float]


class ScoreResponse(BaseModel):
    lat: float
    lon: float
    safety_score: float
    safety_grade: str
    safety_label: str
    safety_color: str
    hour: int


class ReportResponse(BaseModel):
    status: str
    message: str
    lat: float
    lon: float


class HeatmapResponse(BaseModel):
    points: List[List[float]]   # [lat, lon, score]
    count: int


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    graph_loaded: bool
    version: str
