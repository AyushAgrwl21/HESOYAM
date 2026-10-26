"""Health route. It reports configuration and cache presence, and does not call Elexon."""

from fastapi import APIRouter, Request

from app.analytics.cutoff_policy import PILOT_CUTOFF_BASIS
from app.attribution import BMRS_DATA_ATTRIBUTION, BMRS_DATA_LICENCE_URL
from app.data_access.sqlite_cache import inspect_cache
from app.schemas.health import HealthResponse
from app.settings import Settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
@router.get("/api/health", response_model=HealthResponse, include_in_schema=False)
def read_service_health(request: Request) -> HealthResponse:
    """Return the configured study window, the pilot cutoff, and whether a cache is present."""
    application_settings: Settings = request.app.state.settings
    cache_inspection = inspect_cache(application_settings.resolved_cache_path)
    analytics_status = "ready" if cache_inspection.status == "present" else "unavailable"
    return HealthResponse(
        status="ok",
        service_name="wind-procurement-api",
        study_start=application_settings.study_start,
        study_end=application_settings.study_end,
        fuel_type=application_settings.fuel_type,
        decision_timezone=application_settings.decision_timezone,
        decision_cutoff_local=application_settings.decision_cutoff_local,
        cutoff_basis=PILOT_CUTOFF_BASIS,
        elexon_base_url=application_settings.elexon_base_url,
        elexon_request_status="not_called",
        analytics_status=analytics_status,
        cache_status=cache_inspection.status,
        cache_fetched_at_utc=cache_inspection.fetched_at_utc,
        ingestion_coverage_status=cache_inspection.ingestion_coverage_status,
        openapi_url="/openapi.json",
        docs_url="/docs",
        data_attribution=BMRS_DATA_ATTRIBUTION,
        data_licence_url=BMRS_DATA_LICENCE_URL,
    )
