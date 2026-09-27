"""POST /report and GET /report/count - community reports of unsafe spots."""

import csv
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.models.request import ReportRequest
from api.models.response import ReportResponse

log = logging.getLogger("api.report")
router = APIRouter(prefix="/report", tags=["reporting"])

REPORTS = Path("data/raw/user_reports.csv")
COLUMNS = ["timestamp", "lat", "lon", "category", "description", "hour"]


@router.post("/", response_model=ReportResponse)
async def post_report(req: ReportRequest):
    """Appends the report to data/raw/user_reports.csv."""
    try:
        REPORTS.parent.mkdir(parents=True, exist_ok=True)
        is_new_file = not REPORTS.exists()
        now = datetime.now()

        with open(REPORTS, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if is_new_file:
                writer.writerow(COLUMNS)
            writer.writerow([now.isoformat(), req.lat, req.lon, req.category,
                             req.description, req.hour or now.hour])

        log.info("Report saved at (%.4f, %.4f): %s", req.lat, req.lon, req.category)
        return ReportResponse(
            status="recorded",
            message="Thank you. Your report helps make routes safer.",
            lat=req.lat,
            lon=req.lon,
        )
    except Exception as exc:
        log.error("Could not save report: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/count")
async def get_report_count():
    """Number of reports saved so far."""
    if not REPORTS.exists():
        return {"count": 0}
    with open(REPORTS, "r") as fh:
        rows = sum(1 for _ in fh) - 1   # minus the header
    return {"count": max(0, rows)}
