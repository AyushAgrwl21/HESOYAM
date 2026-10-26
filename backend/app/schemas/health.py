from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Configuration report. It contains no generation measurements."""

    status: Literal["ok"]
    service_name: Literal["wind-procurement-api"]
    study_start: date
    study_end: date
    fuel_type: Literal["WIND"]
    decision_timezone: str
    decision_cutoff_local: str = Field(
        description="Local clock time on the day before each delivery date."
    )
    cutoff_basis: Literal["pilot_assumption"]
    elexon_base_url: str
    elexon_request_status: Literal["not_called"]
    analytics_status: Literal["ready", "unavailable"]
    cache_status: Literal["present", "missing", "unreadable"]
    cache_fetched_at_utc: str | None
    ingestion_coverage_status: Literal["complete", "incomplete"] | None
    openapi_url: Literal["/openapi.json"]
    docs_url: Literal["/docs"]
    data_attribution: str
    data_licence_url: str


class ErrorResponse(BaseModel):
    """Actionable failure payload. It does not include a stack trace."""

    error_code: str
    detail: str
