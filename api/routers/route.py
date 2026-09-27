"""
GET /route - safe and fast routes between two points in a city.

Supports four travel modes (car, motorcycle, walking, cycling) and adds
turn-by-turn directions to both routes.
"""

import asyncio
import logging
import math

from fastapi import APIRouter, HTTPException, Query

from routing.city_router import (
    CityPipelineCancelled,
    begin_latest_city_pipeline,
    detect_city,
    route_in_city,
)
from routing.demo_cache import available_cities, find_route

log = logging.getLogger("api.route")
router = APIRouter(prefix="/route", tags=["routing"])

SUPPORTED_MODES = ("car", "motorcycle", "walking", "cycling")
DEFAULT_ALPHA = 0.7

# Safety weight used for each mode when the caller keeps the default alpha.
MODE_ALPHA = {
    "car": 0.7,
    "motorcycle": 0.75,
    "walking": 0.90,
    "cycling": 0.85,
}


@router.get("/")
async def get_route(
    origin_lat: float = Query(...),
    origin_lon: float = Query(...),
    dest_lat: float = Query(...),
    dest_lon: float = Query(...),
    alpha: float = Query(DEFAULT_ALPHA, ge=0, le=1),
    hour: int = Query(22, ge=0, le=23),
    city: str = Query("Bengaluru"),
    auto_detect: bool = Query(False),
    mode: str = Query("car", description="car, motorcycle, walking or cycling"),
):
    log.info("Route request for %s: (%.4f, %.4f) -> (%.4f, %.4f), mode=%s hour=%s alpha=%s",
             city, origin_lat, origin_lon, dest_lat, dest_lon, mode, hour, alpha)
    try:
        if mode not in SUPPORTED_MODES:
            log.warning("Unknown mode '%s', using car", mode)
            mode = "car"

        if auto_detect or city == "auto":
            city = detect_city(origin_lat, origin_lon)
            log.info("Detected city: %s", city)

        available = available_cities()
        if not any(name.lower() == city.lower() for name in available):
            nearest = _find_nearest_available(origin_lat, origin_lon, available)
            log.warning("No data for %s; nearest available city is %s", city, nearest)
            return {
                "error": "service_unavailable",
                "message": f"Service not yet available in {city}.",
                "suggestion": f"Nearest available city: {nearest}",
                "available_cities": available[:10],
                "city_requested": city,
            }

        # A caller who leaves alpha at its default gets the mode's own default.
        effective_alpha = alpha if alpha != DEFAULT_ALPHA else MODE_ALPHA.get(mode, DEFAULT_ALPHA)

        generation = begin_latest_city_pipeline(city)
        result = find_route(city, origin_lat, origin_lon, dest_lat, dest_lon,
                            effective_alpha, hour, mode)
        if result is None:
            result = await asyncio.to_thread(
                route_in_city, city, origin_lat, origin_lon, dest_lat, dest_lon,
                effective_alpha, hour, mode, generation,
            )
        if "error" in result:
            log.error("Routing failed: %s", result["error"])
            raise HTTPException(status_code=404, detail=result["error"])

        for key in ("safe_route", "fast_route"):
            result[key]["directions"] = generate_directions(result[key]["segments"], result[key]["coords"])

        log.info("Routes ready: safe %.2f km (score %s), fast %.2f km (score %s)",
                 result["safe_route"]["total_dist_km"], result["safe_route"].get("avg_safety_score"),
                 result["fast_route"]["total_dist_km"], result["fast_route"].get("avg_safety_score"))
        return result

    except CityPipelineCancelled as exc:
        log.info("Route request replaced by a newer city selection: %s", exc)
        raise HTTPException(
            status_code=409,
            detail="City changed while processing route. Please retry with the latest city selection.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Route error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _find_nearest_available(lat, lon, available_cities):
    """Available city whose bbox centre is closest to (lat, lon)."""
    from ingestion.fetch_india_graph import CITY_BBOXES

    best = available_cities[0] if available_cities else "Bengaluru"
    best_distance = float("inf")
    for name in available_cities:
        bbox = CITY_BBOXES.get(name)
        if not bbox:
            continue
        centre_lat = (bbox["north"] + bbox["south"]) / 2
        centre_lon = (bbox["east"] + bbox["west"]) / 2
        distance = ((lat - centre_lat) ** 2 + (lon - centre_lon) ** 2) ** 0.5
        if distance < best_distance:
            best, best_distance = name, distance
    return best


# Turn-by-turn directions ------------------------------------------------------------

def _turn_instruction(angle: float) -> str:
    """Wording for a change of heading in degrees (negative = left)."""
    if abs(angle) > 150:
        return "U-turn"
    if angle < -60:
        return "Turn sharp left"
    if angle < -20:
        return "Turn left"
    if angle < -5:
        return "Keep left"
    if angle > 60:
        return "Turn sharp right"
    if angle > 20:
        return "Turn right"
    if angle > 5:
        return "Keep right"
    return "Continue straight"


def _turn_type(angle: float) -> str:
    if angle < -60:
        return "sharp_left"
    if angle < -20:
        return "left"
    if angle < -5:
        return "slight_left"
    if angle > 60:
        return "sharp_right"
    if angle > 20:
        return "right"
    if angle > 5:
        return "slight_right"
    return "straight"


def _bearing(start: list, end: list) -> float:
    """Compass bearing in degrees from one [lat, lon] point to another."""
    lat1, lat2 = math.radians(start[0]), math.radians(end[0])
    d_lon = math.radians(end[1] - start[1])
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    return math.degrees(math.atan2(x, y))


def _turn_angle(coords: list, index: int) -> float:
    """Change of heading from segment index to the next (negative = left).

    Segment i runs from coords[i] to coords[i + 1].
    """
    before = _bearing(coords[index], coords[index + 1])
    after = _bearing(coords[index + 1], coords[index + 2])
    return (after - before + 180) % 360 - 180


def _step(number: int, text: str, segment: dict, kind: str, moving: bool = True) -> dict:
    return {
        "step": number,
        "instruction": text,
        "distance_m": segment.get("length_m", 0) if moving else 0,
        "duration_s": segment.get("travel_time_s", 0) if moving else 0,
        "safety_score": segment.get("safety_score", 50),
        "safety_grade": segment.get("safety_grade", "C"),
        "safety_color": segment.get("safety_color", "#f59e0b"),
        "type": kind,
    }


def generate_directions(segments: list, coords: list) -> list:
    """Turn-by-turn steps; consecutive segments on the same named road are merged.

    coords are the route's [lat, lon] nodes, one more than the segments.
    """
    if not segments or len(segments) < 2:
        return []

    first_road = segments[0].get("name", "the road") or "the road"
    directions = [_step(1, f"Start on {first_road}", segments[0], "start")]

    number = 2
    for i in range(len(segments) - 1):
        current, following = segments[i], segments[i + 1]
        current_name = str(current.get("name", "") or "")
        following_name = str(following.get("name", "") or "")
        if current_name and current_name == following_name:
            continue

        angle = _turn_angle(coords, i)
        road = following_name or f"unnamed {following.get('highway', 'road')}"
        step = _step(number, f"{_turn_instruction(angle)} onto {road}", following, _turn_type(angle))
        step["road_name"] = road
        directions.append(step)
        number += 1

    directions.append(_step(number, "Arrive at your destination", segments[-1], "arrive", moving=False))
    return directions
