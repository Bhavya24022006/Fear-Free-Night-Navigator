"""
FastAPI application.

Start the server from the repository root:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

Interactive documentation is served at /docs (Swagger) and /redoc.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import cities, heatmap, report, route, score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("api.main")

APP_NAME = "Fear-Free Night Navigator"
APP_VERSION = "1.0.0"


def _legacy_graph_status() -> tuple[bool, int]:
    """(loaded, edge count) for the Bengaluru graph used by /score."""
    try:
        from routing.graph import get_graph

        G = get_graph()
        return True, len(G.edges)
    except Exception:
        log.info("Optional single-city graph for /score not found; routing uses data/india/city_graphs.")
        return False, 0


def _model_status() -> bool:
    try:
        from ai.ml.predict import load_model

        load_model()
        return True
    except Exception as exc:
        log.warning("Model not available: %s", exc)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warms the slow-to-load resources once at start-up."""
    log.info("Starting %s ...", APP_NAME)
    _legacy_graph_status()
    _model_status()
    log.info("API ready.")
    yield
    log.info("API shutting down.")


app = FastAPI(
    title=APP_NAME,
    description=(
        "Safety-aware routing for Indian cities. Routes are ranked by a "
        "psychological safety score as well as travel time."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (route, score, report, heatmap, cities):
    app.include_router(module.router)

if Path("frontend").exists():
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/", tags=["health"])
async def root():
    """Service information and whether the model and legacy graph are loaded."""
    graph_loaded, n_edges = _legacy_graph_status()
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "city": "Bengaluru, Karnataka, India",
        "model_loaded": _model_status(),
        "graph_loaded": graph_loaded,
        "n_edges": n_edges,
        "endpoints": {
            "route": "/route?origin_lat=12.97&origin_lon=77.60&dest_lat=12.93&dest_lon=77.62",
            "score": "/score?lat=12.97&lon=77.60",
            "report": "/report",
            "heatmap": "/heatmap",
            "docs": "/docs",
        },
    }


@app.get("/health", tags=["health"])
async def health():
    """Lightweight liveness check."""
    return {"status": "ok"}
