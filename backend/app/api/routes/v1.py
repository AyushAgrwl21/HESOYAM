"""Cached study reads. These routes do not call Elexon and do not place orders."""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.http_errors import CodedHTTPException
from app.api.study_queries import InvalidStudyQuery, StudyWindowQuery, VintageQuery, resolve_vintage_target, resolve_window
from app.api.study_service import (
    CacheMissing,
    CacheUnreadable,
    UpstreamUnavailable,
    build_accuracy,
    build_data_quality,
    build_series,
    build_summary,
    build_vintages,
    known_interval_starts,
)
from app.schemas.read_api import (
    AccuracyResponse,
    DataQualityResponse,
    SeriesResponse,
    SummaryResponse,
    VintageResponse,
)
from app.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["study"])


@router.get("/summary", response_model=SummaryResponse)
def read_summary(
    request: Request,
    query: Annotated[StudyWindowQuery, Query()],
) -> SummaryResponse:
    """Decision-time metrics for the requested dates, plus a labelled latest-available score."""
    window = _resolve(request, query)
    return _read(lambda: build_summary(_settings(request), window))


@router.get("/series", response_model=SeriesResponse)
def read_series(
    request: Request,
    query: Annotated[StudyWindowQuery, Query()],
) -> SeriesResponse:
    """Decision-time forecast and actual at each settlement start in the requested window."""
    window = _resolve(request, query)
    return _read(lambda: build_series(_settings(request), window))


@router.get("/accuracy", response_model=AccuracyResponse)
def read_accuracy(
    request: Request,
    query: Annotated[StudyWindowQuery, Query()],
) -> AccuracyResponse:
    """Decision-time metrics for the window, each delivery day, and each settlement period."""
    window = _resolve(request, query)
    return _read(lambda: build_accuracy(_settings(request), window))


@router.get("/forecast-vintages", response_model=VintageResponse)
def read_forecast_vintages(
    request: Request,
    query: Annotated[VintageQuery, Query()],
) -> VintageResponse:
    """Every cached publication of one target, including publications after the cutoff."""
    settings = _settings(request)
    try:
        window = resolve_window(settings, query)
        if query.start_time:
            target_start_time_utc = resolve_vintage_target(settings, query, {})
        else:
            starts = known_interval_starts(settings, window.decision_cutoff_local)
            target_start_time_utc = resolve_vintage_target(settings, query, starts)
    except InvalidStudyQuery as error:
        raise CodedHTTPException(422, "invalid_request", str(error)) from error
    except (CacheMissing, CacheUnreadable, UpstreamUnavailable) as error:
        raise _cache_error(error) from error
    return _read(lambda: build_vintages(settings, window, target_start_time_utc))


@router.get("/data-quality", response_model=DataQualityResponse)
def read_data_quality(
    request: Request,
    query: Annotated[StudyWindowQuery, Query()],
) -> DataQualityResponse:
    """Retrieval completeness for the cached extract and coverage of the requested window."""
    window = _resolve(request, query)
    return _read(lambda: build_data_quality(_settings(request), window))


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _resolve(request: Request, query: StudyWindowQuery):
    try:
        return resolve_window(_settings(request), query)
    except InvalidStudyQuery as error:
        raise CodedHTTPException(422, "invalid_request", str(error)) from error


def _read(build):
    try:
        return build()
    except (CacheMissing, CacheUnreadable, UpstreamUnavailable) as error:
        raise _cache_error(error) from error


def _cache_error(error: Exception) -> CodedHTTPException:
    if isinstance(error, CacheMissing):
        return CodedHTTPException(409, "cache_missing", str(error))
    if isinstance(error, CacheUnreadable):
        return CodedHTTPException(503, "cache_unreadable", str(error))
    return CodedHTTPException(
        502,
        "upstream_unavailable",
        f"{error} The cache was not replaced with an empty dataset.",
    )
