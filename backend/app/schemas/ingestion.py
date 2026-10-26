"""Validation report for one ingestion run. It is not a forecast-error score."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class DuplicateAccounting(BaseModel):
    natural_key: str
    policy: str
    identical_copies_collapsed: int = Field(ge=0)
    conflicting_key_groups: int = Field(ge=0)
    conflicting_records_retained: int = Field(ge=0)


class GenerationQuality(BaseModel):
    missing_generation_records: int = Field(ge=0)
    negative_generation_records: int = Field(ge=0)


class TimestampBounds(BaseModel):
    minimum_utc: datetime | None
    maximum_utc: datetime | None


class ActualIngestionQuality(BaseModel):
    records_received: int = Field(ge=0)
    malformed_records: int = Field(ge=0)
    records_parsed: int = Field(ge=0)
    records_retained: int = Field(ge=0)
    excluded_non_wind_records: int = Field(ge=0)
    target_timestamps: TimestampBounds
    duplicates: DuplicateAccounting
    generation: GenerationQuality
    missing_half_hour_start_times_utc: list[str]
    unexpected_start_times_utc: list[str]
    settlement_period_mismatches: int = Field(ge=0)
    unexpected_dataset_records: int = Field(ge=0)
    malformed_examples: list[str]


class ForecastIngestionQuality(BaseModel):
    records_received: int = Field(ge=0)
    malformed_records: int = Field(ge=0)
    records_parsed: int = Field(ge=0)
    records_outside_study_window: int = Field(ge=0)
    records_retained: int = Field(ge=0)
    vintage_count: int = Field(ge=0)
    target_timestamps: TimestampBounds
    publication_timestamps: TimestampBounds
    duplicates: DuplicateAccounting
    generation: GenerationQuality
    observed_start_time_spacings_minutes: list[int]
    vintages_with_uneven_spacing: int = Field(ge=0)
    unexpected_dataset_records: int = Field(ge=0)
    malformed_examples: list[str]


class IngestionReport(BaseModel):
    """Provenance and coverage for the cached extract. Forecast error is absent."""

    fetched_at_utc: datetime
    elexon_base_url: str
    study_start: date
    study_end: date
    fuel_type: Literal["WIND"]
    decision_timezone: str
    actual_stream_path: str
    forecast_stream_path: str
    actual_query: dict[str, str]
    forecast_query: dict[str, str]
    request_strategy: Literal["single_query", "chunked_after_failure"]
    pagination: str
    rate_limit: str
    attribution: str
    data_licence_url: str
    cache_path: str
    coverage_status: Literal["complete", "incomplete"]
    coverage_limitations: list[str]
    evaluation_status: Literal["not_calculated"]
    actuals: ActualIngestionQuality
    forecasts: ForecastIngestionQuality
