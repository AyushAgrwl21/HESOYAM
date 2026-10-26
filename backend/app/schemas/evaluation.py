"""Decision-time evaluation models.

These models are the analytical result. They are not an HTTP response and they
contain a score only when the supplied rows support one.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.analytics.cutoff_policy import PILOT_CUTOFF_BASIS

ComparisonRole = Literal["decision_time", "latest_available"]
MatchStatus = Literal[
    "matched",
    "missing_forecast",
    "missing_actual",
    "missing_both",
    "excluded_conflicting_forecast",
    "excluded_conflicting_actual",
    "excluded_conflicting_records",
]
WapeStatus = Literal[
    "calculated",
    "undefined_non_positive_actual_sum",
    "not_applicable_no_matches",
]


class ErrorMetrics(BaseModel):
    """Summaries over matched intervals. Unmatched intervals are not zeros."""

    matched_interval_count: int = Field(ge=0)
    mean_error_mw: float | None
    mean_absolute_error_mw: float | None
    root_mean_squared_error_mw: float | None
    weighted_absolute_percentage_error_percent: float | None
    wape_status: WapeStatus
    generation_unit: Literal["MW"]
    error_unit: Literal["MW"]


class CoverageStatusCounts(BaseModel):
    """Non-overlapping statuses. Their sum is the denominator."""

    matched: int = Field(ge=0)
    missing_forecast: int = Field(ge=0)
    missing_actual: int = Field(ge=0)
    missing_both: int = Field(ge=0)
    excluded_conflicting_forecast: int = Field(ge=0)
    excluded_conflicting_actual: int = Field(ge=0)
    excluded_conflicting_records: int = Field(ge=0)


class CoverageReport(BaseModel):
    """Matched and missing counts over one explicit denominator.

    intervals_without_usable_forecast and intervals_without_usable_actual
    overlap on empty intervals. status_counts is the partition that reconciles
    to the denominator.
    """

    denominator_definition: str
    denominator_interval_count: int = Field(ge=0)
    matched_interval_count: int = Field(ge=0)
    intervals_without_usable_forecast: int = Field(ge=0)
    intervals_without_usable_actual: int = Field(ge=0)
    coverage_percent: float | None
    status_counts: CoverageStatusCounts


class IntervalScore(BaseModel):
    """One settlement start, with the selected vintage kept for audit."""

    start_time_utc: str
    delivery_date: date
    settlement_period: int = Field(ge=1, le=50)
    local_start_time: str
    cutoff_utc: datetime
    actual_generation_mw: int | None
    selected_publish_time_utc: str | None
    forecast_generation_mw: int | None
    signed_error_mw: int | None
    absolute_error_mw: int | None
    match_status: MatchStatus


class GroupAccuracy(BaseModel):
    """Metrics for one delivery day or one settlement period."""

    metrics: ErrorMetrics
    coverage: CoverageReport
    selected_publish_times_utc: list[str]


class DayAccuracy(GroupAccuracy):
    delivery_date: date
    cutoff_utc: datetime
    cutoff_local: str


class SettlementPeriodAccuracy(GroupAccuracy):
    settlement_period: int = Field(ge=1, le=50)
    local_start_time: str | None


class VintagePoint(BaseModel):
    """One publication of one target, including publications the decision cannot use."""

    publish_time_utc: str
    generation_mw: int | None
    eligible_at_decision: bool
    selected_for_decision: bool
    selected_for_latest_available: bool
    conflict: bool


class VintageEvolution(BaseModel):
    """Every supplied vintage of one target startTime."""

    target_start_time_utc: str
    delivery_date: date
    cutoff_utc: datetime
    outside_scored_grid: bool
    points: list[VintagePoint]
    note: str


class ScoringDuplicateReport(BaseModel):
    policy: str
    identical_forecast_copies_collapsed: int = Field(ge=0)
    conflicting_forecast_keys: int = Field(ge=0)
    conflicting_forecast_rows: int = Field(ge=0)
    identical_actual_copies_collapsed: int = Field(ge=0)
    conflicting_actual_keys: int = Field(ge=0)
    conflicting_actual_rows: int = Field(ge=0)


class InputAccounting(BaseModel):
    actual_rows: int = Field(ge=0)
    forecast_rows: int = Field(ge=0)
    actual_rows_outside_study: int = Field(ge=0)
    forecast_rows_outside_study: int = Field(ge=0)
    misaligned_actual_rows: int = Field(ge=0)
    duplicates: ScoringDuplicateReport


class ComparisonBlock(BaseModel):
    """One complete comparison. The two roles must not be read as the same score."""

    role: ComparisonRole
    available_to_purchaser: bool
    description: str
    metrics: ErrorMetrics
    coverage: CoverageReport
    by_delivery_day: list[DayAccuracy]
    by_settlement_period: list[SettlementPeriodAccuracy]
    distinct_selected_publish_times_utc: list[str]
    selections_after_cutoff: int = Field(ge=0)
    series: list[IntervalScore]


class DecisionEvaluation(BaseModel):
    """Primary decision-time score and a separate latest-available comparison."""

    cutoff_basis: Literal["pilot_assumption"] = PILOT_CUTOFF_BASIS
    decision_timezone: str
    decision_cutoff_local: str
    cutoff_convention: str
    generation_unit: Literal["MW"]
    study_start: date
    study_end: date
    inputs: InputAccounting
    primary: ComparisonBlock
    latest_available: ComparisonBlock
    vintage_evolution: VintageEvolution | None

    @model_validator(mode="after")
    def comparisons_stay_distinct(self) -> "DecisionEvaluation":
        if self.primary.role != "decision_time" or not self.primary.available_to_purchaser:
            raise ValueError("The primary comparison must be the decision-time score.")
        if self.primary.selections_after_cutoff != 0:
            raise ValueError(
                "A forecast published after the cutoff entered the primary comparison."
            )
        if (
            self.latest_available.role != "latest_available"
            or self.latest_available.available_to_purchaser
        ):
            raise ValueError(
                "The latest-available comparison must stay labelled as information "
                "the purchaser did not have."
            )
        return self
