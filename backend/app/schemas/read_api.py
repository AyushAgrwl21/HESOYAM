"""Stable JSON shapes for the read API.

These responses describe the cached study. They do not recommend a trade
and they do not place an order.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.analytics.cutoff_policy import METRIC_DEFINITIONS, NULL_GENERATION_MEANING, REFRESH_STRATEGY
from app.schemas.evaluation import (
    ComparisonRole,
    CoverageReport,
    DayAccuracy,
    ErrorMetrics,
    MatchStatus,
    ScoringDuplicateReport,
    SettlementPeriodAccuracy,
    VintageEvolution,
)


class RequestedWindow(BaseModel):
    """The slice the caller asked for, after defaults were applied."""

    delivery_start: date
    delivery_end: date
    decision_timezone: str
    decision_cutoff_local: str
    cutoff_basis: Literal["pilot_assumption"]
    cutoff_convention: str
    settlement_period: int | None = Field(default=None, ge=1, le=50)
    generation_unit: Literal["MW"]
    error_unit: Literal["MW"]
    null_generation_meaning: str = NULL_GENERATION_MEANING
    metric_definitions: dict[str, str] = METRIC_DEFINITIONS


class SourceProvenance(BaseModel):
    """Where the rows came from. A read does not contact Elexon."""

    fetched_at_utc: str
    live_elexon_request: Literal[False] = False
    refresh_strategy: str = REFRESH_STRATEGY
    data_attribution: str
    data_licence_url: str
    ingestion_coverage_status: Literal["complete", "incomplete"]
    ingestion_limitations: list[str]
    cache_actual_rows: int = Field(ge=0)
    cache_forecast_rows: int = Field(ge=0)
    study_window_matches_request_settings: bool


class ScoreBlock(BaseModel):
    """One comparison. The latest-available block was not available to the purchaser."""

    role: ComparisonRole
    available_to_purchaser: bool
    description: str
    metrics: ErrorMetrics
    coverage: CoverageReport
    distinct_selected_publish_times_utc: list[str]
    selections_after_cutoff: int = Field(ge=0)


class SummaryResponse(BaseModel):
    window: RequestedWindow
    provenance: SourceProvenance
    window_note: str
    primary: ScoreBlock
    latest_available: ScoreBlock
    trading_recommendation: Literal["not_provided"] = "not_provided"

    @model_validator(mode="after")
    def comparisons_stay_distinct(self) -> "SummaryResponse":
        _require_distinct_comparisons(self.primary, self.latest_available)
        return self


class SeriesInterval(BaseModel):
    """One settlement start. Null generation is missing; zero is measured."""

    start_time_utc: str
    delivery_date: date
    settlement_period: int = Field(ge=1, le=50)
    local_start_time: str
    cutoff_utc: datetime
    actual_generation_mw: int | None
    actual_measurement: Literal["measured", "missing"]
    selected_publish_time_utc: str | None
    forecast_generation_mw: int | None
    forecast_measurement: Literal["measured", "missing"]
    signed_error_mw: int | None
    absolute_error_mw: int | None
    match_status: MatchStatus
    generation_unit: Literal["MW"] = "MW"
    error_unit: Literal["MW"] = "MW"


class SeriesResponse(BaseModel):
    window: RequestedWindow
    provenance: SourceProvenance
    window_note: str
    comparison: Literal["decision_time"] = "decision_time"
    available_to_purchaser: Literal[True] = True
    interval_count: int = Field(ge=0)
    truncated: Literal[False] = False
    intervals: list[SeriesInterval]
    trading_recommendation: Literal["not_provided"] = "not_provided"


class AccuracyResponse(BaseModel):
    window: RequestedWindow
    provenance: SourceProvenance
    window_note: str
    primary: ScoreBlock
    latest_available: ScoreBlock
    by_delivery_day: list[DayAccuracy]
    by_settlement_period: list[SettlementPeriodAccuracy]
    trading_recommendation: Literal["not_provided"] = "not_provided"

    @model_validator(mode="after")
    def comparisons_stay_distinct(self) -> "AccuracyResponse":
        _require_distinct_comparisons(self.primary, self.latest_available)
        return self


class VintageResponse(BaseModel):
    window: RequestedWindow
    provenance: SourceProvenance
    evolution: VintageEvolution
    primary_score_uses_only_eligible_points: Literal[True] = True
    trading_recommendation: Literal["not_provided"] = "not_provided"


def _require_distinct_comparisons(primary: ScoreBlock, latest_available: ScoreBlock) -> None:
    if primary.role != "decision_time" or not primary.available_to_purchaser:
        raise ValueError("The primary comparison must be the decision-time score.")
    if primary.selections_after_cutoff != 0:
        raise ValueError("A forecast published after the cutoff entered the primary comparison.")
    if latest_available.role != "latest_available" or latest_available.available_to_purchaser:
        raise ValueError(
            "The latest-available comparison must stay labelled as information the purchaser did not have."
        )


class ExampleList(BaseModel):
    count: int = Field(ge=0)
    examples: list[str]


class RetrievalQuality(BaseModel):
    """Ingestion checks for the cached extract. This is not a forecast score."""

    coverage_status: Literal["complete", "incomplete"]
    coverage_limitations: list[str]
    actual_rows_retained: int = Field(ge=0)
    forecast_rows_retained: int = Field(ge=0)
    forecast_rows_outside_study_window: int = Field(ge=0)
    missing_half_hour_starts: ExampleList
    unexpected_actual_starts: ExampleList
    actual_duplicate_conflicts: int = Field(ge=0)
    forecast_duplicate_conflicts: int = Field(ge=0)
    null_actual_generation_rows: int = Field(ge=0)
    null_forecast_generation_rows: int = Field(ge=0)
    pagination: str
    request_strategy: str


class DataQualityResponse(BaseModel):
    window: RequestedWindow
    provenance: SourceProvenance
    retrieval: RetrievalQuality
    scoring_duplicates: ScoringDuplicateReport
    requested_window_coverage: CoverageReport
    requested_window_note: str
    trading_recommendation: Literal["not_provided"] = "not_provided"
