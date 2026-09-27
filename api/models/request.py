"""Request bodies accepted by the API."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

REPORT_CATEGORIES = {"unsafe", "harassment", "poor_lighting", "crime", "other"}


class RouteRequest(BaseModel):
    """Two points plus the user's safety preference and departure hour."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "origin_lat": 12.9767,
            "origin_lon": 77.6009,
            "dest_lat": 12.9352,
            "dest_lon": 77.6245,
            "alpha": 0.7,
            "hour": 22,
        }
    })

    origin_lat: float = Field(..., ge=-90, le=90, description="Start latitude")
    origin_lon: float = Field(..., ge=-180, le=180, description="Start longitude")
    dest_lat: float = Field(..., ge=-90, le=90, description="Destination latitude")
    dest_lon: float = Field(..., ge=-180, le=180, description="Destination longitude")
    alpha: float = Field(0.7, ge=0.0, le=1.0, description="Weight on safety, 0 to 1")
    hour: int = Field(22, ge=0, le=23, description="Hour of travel, 0 to 23")

    @field_validator("alpha")
    @classmethod
    def _two_decimals(cls, value: float) -> float:
        return round(value, 2)


class ScoreRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    hour: int = Field(22, ge=0, le=23)


class ReportRequest(BaseModel):
    """A user report about an unsafe spot."""

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    description: str = Field(..., min_length=5, max_length=500)
    category: str = Field("unsafe", description="unsafe, harassment, poor_lighting, crime or other")
    hour: Optional[int] = Field(None, ge=0, le=23)

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        return value if value in REPORT_CATEGORIES else "other"
