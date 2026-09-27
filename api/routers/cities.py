"""GET /cities and GET /cities/detect - which cities can be routed."""

import logging

from fastapi import APIRouter, Query

log = logging.getLogger("api.cities")
router = APIRouter(prefix="/cities", tags=["cities"])

DEFAULT_CITY = "Bengaluru"


@router.get("/")
async def get_cities():
    """Cities that have a road graph or stored demo routes on disk."""
    try:
        from routing.demo_cache import available_cities

        cities = available_cities()
        log.info("%d cities available", len(cities))
        return {"cities": cities, "total": len(cities), "default": DEFAULT_CITY}
    except Exception as exc:
        log.error("Could not list cities: %s", exc)
        return {"cities": [DEFAULT_CITY], "total": 1, "default": DEFAULT_CITY}


@router.get("/detect")
async def detect_city(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """City that contains (or is nearest to) the given position."""
    try:
        from routing.city_router import detect_city as locate

        return {"city": locate(lat, lon), "lat": lat, "lon": lon}
    except Exception as exc:
        log.error("City detection failed: %s", exc)
        return {"city": DEFAULT_CITY, "lat": lat, "lon": lon}
