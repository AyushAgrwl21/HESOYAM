"""Read the cached study and score a requested window.

The cache of prepared studies holds at most four cutoff variants. A missing
cache and a failed read are not stored as empty generation rows.
"""

import sqlite3
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock

from pydantic import ValidationError

from app.analytics.cutoff_policy import (
    CUTOFF_CONVENTION,
    ERROR_UNIT,
    GENERATION_UNIT,
    PILOT_CUTOFF_BASIS,
    REQUESTED_WINDOW_DENOMINATOR,
)
from app.analytics.forecast_evaluation import (
    LATEST_AVAILABLE_DESCRIPTION,
    PRIMARY_DESCRIPTION,
    describe_forecast_vintages,
    evaluate_decision_time_forecast,
    summarise_scored_intervals,
)
from app.api.study_queries import ResolvedWindow, describe_window
from app.attribution import BMRS_DATA_ATTRIBUTION, BMRS_DATA_LICENCE_URL
from app.data_access.errors import ElexonClientError
from app.data_access.sqlite_cache import (
    CachedStudyExtract,
    inspect_cache,
    load_cached_extract,
    load_ingestion_report,
)
from app.schemas.evaluation import ComparisonRole, DecisionEvaluation, IntervalScore
from app.schemas.ingestion import IngestionReport
from app.schemas.read_api import (
    AccuracyResponse,
    DataQualityResponse,
    ExampleList,
    RequestedWindow,
    RetrievalQuality,
    ScoreBlock,
    SeriesInterval,
    SeriesResponse,
    SourceProvenance,
    SummaryResponse,
    VintageResponse,
)
from app.settings import Settings

_PREPARED_STUDIES: OrderedDict[tuple[str, str, str, str, str, str], "PreparedStudy"] = OrderedDict()
_PREPARED_STUDY_LOCK = Lock()
_PREPARED_STUDY_LIMIT = 4


class CacheMissing(FileNotFoundError):
    """The read has no successful extract to score."""


class CacheUnreadable(RuntimeError):
    """The cache file exists but is not a usable successful extract."""


class UpstreamUnavailable(RuntimeError):
    """An upstream failure was not turned into an empty dataset."""


@dataclass(frozen=True)
class PreparedStudy:
    extract: CachedStudyExtract
    report: IngestionReport
    evaluation: DecisionEvaluation


def prepare_study(settings: Settings, cutoff_local: str) -> PreparedStudy:
    """Load and score the configured study, reusing a recent success."""
    cache_path = settings.resolved_cache_path
    inspection = inspect_cache(cache_path)
    if inspection.status == "missing":
        raise CacheMissing(inspection.detail or "No study cache is available.")
    if inspection.status != "present" or inspection.fetched_at_utc is None:
        raise CacheUnreadable(inspection.detail or "The study cache could not be read.")
    cache_key = (
        str(cache_path.resolve()),
        inspection.fetched_at_utc,
        cutoff_local,
        settings.decision_timezone,
        settings.study_start.isoformat(),
        settings.study_end.isoformat(),
    )
    with _PREPARED_STUDY_LOCK:
        prepared = _PREPARED_STUDIES.get(cache_key)
        if prepared is not None:
            _PREPARED_STUDIES.move_to_end(cache_key)
            return prepared
    prepared = _load_prepared_study(settings, cache_path, cutoff_local)
    with _PREPARED_STUDY_LOCK:
        _PREPARED_STUDIES[cache_key] = prepared
        _PREPARED_STUDIES.move_to_end(cache_key)
        while len(_PREPARED_STUDIES) > _PREPARED_STUDY_LIMIT:
            _PREPARED_STUDIES.popitem(last=False)
    return prepared


def clear_prepared_studies() -> None:
    """Drop scored studies held in this process. Tests use this between cases."""
    with _PREPARED_STUDY_LOCK:
        _PREPARED_STUDIES.clear()


def build_summary(settings: Settings, window: ResolvedWindow) -> SummaryResponse:
    prepared = prepare_study(settings, window.decision_cutoff_local)
    primary_rows = _filter_series(prepared.evaluation.primary.series, window)
    latest_rows = _filter_series(prepared.evaluation.latest_available.series, window)
    primary_summary = _summary_for(settings, window, primary_rows)
    latest_summary = _summary_for(settings, window, latest_rows)
    _reject_leaked_primary(primary_summary.selections_after_cutoff)
    return SummaryResponse(
        window=_requested_window(settings, window),
        provenance=_provenance(settings, prepared),
        window_note=describe_window(
            window.delivery_start,
            window.delivery_end,
            window.settlement_period,
            len(primary_rows),
        ),
        primary=_score_block(
            role="decision_time",
            available_to_purchaser=True,
            description=PRIMARY_DESCRIPTION,
            summary=primary_summary,
        ),
        latest_available=_score_block(
            role="latest_available",
            available_to_purchaser=False,
            description=LATEST_AVAILABLE_DESCRIPTION,
            summary=latest_summary,
        ),
    )


def build_series(settings: Settings, window: ResolvedWindow) -> SeriesResponse:
    prepared = prepare_study(settings, window.decision_cutoff_local)
    rows = _filter_series(prepared.evaluation.primary.series, window)
    summary = _summary_for(settings, window, rows)
    _reject_leaked_primary(summary.selections_after_cutoff)
    return SeriesResponse(
        window=_requested_window(settings, window),
        provenance=_provenance(settings, prepared),
        window_note=describe_window(
            window.delivery_start,
            window.delivery_end,
            window.settlement_period,
            len(rows),
        ),
        interval_count=len(rows),
        intervals=[_series_interval(row) for row in rows],
    )


def build_accuracy(settings: Settings, window: ResolvedWindow) -> AccuracyResponse:
    prepared = prepare_study(settings, window.decision_cutoff_local)
    primary_rows = _filter_series(prepared.evaluation.primary.series, window)
    latest_rows = _filter_series(prepared.evaluation.latest_available.series, window)
    primary_summary = _summary_for(settings, window, primary_rows)
    latest_summary = _summary_for(settings, window, latest_rows)
    _reject_leaked_primary(primary_summary.selections_after_cutoff)
    return AccuracyResponse(
        window=_requested_window(settings, window),
        provenance=_provenance(settings, prepared),
        window_note=describe_window(
            window.delivery_start,
            window.delivery_end,
            window.settlement_period,
            len(primary_rows),
        ),
        primary=_score_block(
            role="decision_time",
            available_to_purchaser=True,
            description=PRIMARY_DESCRIPTION,
            summary=primary_summary,
        ),
        latest_available=_score_block(
            role="latest_available",
            available_to_purchaser=False,
            description=LATEST_AVAILABLE_DESCRIPTION,
            summary=latest_summary,
        ),
        by_delivery_day=primary_summary.by_delivery_day,
        by_settlement_period=primary_summary.by_settlement_period,
    )


def build_vintages(settings: Settings, window: ResolvedWindow, target_start_time_utc: str) -> VintageResponse:
    prepared = prepare_study(settings, window.decision_cutoff_local)
    evolution = describe_forecast_vintages(
        prepared.extract.forecasts,
        target_start_time_utc=target_start_time_utc,
        study_start=settings.study_start,
        study_end=settings.study_end,
        decision_timezone=settings.decision_timezone,
        decision_cutoff_local=window.decision_cutoff_local,
    )
    requested_window = _requested_window(settings, window).model_copy(
        update={
            "delivery_start": evolution.delivery_date,
            "delivery_end": evolution.delivery_date,
        }
    )
    return VintageResponse(
        window=requested_window,
        provenance=_provenance(settings, prepared),
        evolution=evolution,
    )


def build_data_quality(settings: Settings, window: ResolvedWindow) -> DataQualityResponse:
    prepared = prepare_study(settings, window.decision_cutoff_local)
    rows = _filter_series(prepared.evaluation.primary.series, window)
    summary = _summary_for(settings, window, rows)
    report = prepared.report
    return DataQualityResponse(
        window=_requested_window(settings, window),
        provenance=_provenance(settings, prepared),
        retrieval=RetrievalQuality(
            coverage_status=report.coverage_status,
            coverage_limitations=report.coverage_limitations,
            actual_rows_retained=report.actuals.records_retained,
            forecast_rows_retained=report.forecasts.records_retained,
            forecast_rows_outside_study_window=report.forecasts.records_outside_study_window,
            missing_half_hour_starts=_examples(report.actuals.missing_half_hour_start_times_utc),
            unexpected_actual_starts=_examples(report.actuals.unexpected_start_times_utc),
            actual_duplicate_conflicts=report.actuals.duplicates.conflicting_key_groups,
            forecast_duplicate_conflicts=report.forecasts.duplicates.conflicting_key_groups,
            null_actual_generation_rows=report.actuals.generation.missing_generation_records,
            null_forecast_generation_rows=report.forecasts.generation.missing_generation_records,
            pagination=report.pagination,
            request_strategy=report.request_strategy,
        ),
        scoring_duplicates=prepared.evaluation.inputs.duplicates,
        requested_window_coverage=summary.coverage,
        requested_window_note=describe_window(
            window.delivery_start,
            window.delivery_end,
            window.settlement_period,
            len(rows),
        ),
    )


def known_interval_starts(settings: Settings, cutoff_local: str) -> dict[tuple[date, int], str]:
    """Map a delivery date and settlement period to its UTC start."""
    prepared = prepare_study(settings, cutoff_local)
    return {
        (row.delivery_date, row.settlement_period): row.start_time_utc
        for row in prepared.evaluation.primary.series
    }


def _load_prepared_study(settings: Settings, cache_path: Path, cutoff_local: str) -> PreparedStudy:
    try:
        extract = load_cached_extract(cache_path)
        report = load_ingestion_report(cache_path)
    except FileNotFoundError as error:
        raise CacheMissing(str(error)) from error
    except ElexonClientError as error:
        raise UpstreamUnavailable(str(error)) from error
    except (OSError, ValidationError, sqlite3.Error) as error:
        raise CacheUnreadable(f"The study cache could not be read. {error}") from error
    evaluation = evaluate_decision_time_forecast(
        extract.actuals,
        extract.forecasts,
        study_start=settings.study_start,
        study_end=settings.study_end,
        decision_timezone=settings.decision_timezone,
        decision_cutoff_local=cutoff_local,
    )
    return PreparedStudy(extract=extract, report=report, evaluation=evaluation)


def _filter_series(series: list[IntervalScore], window: ResolvedWindow) -> list[IntervalScore]:
    return [
        row
        for row in series
        if window.delivery_start <= row.delivery_date <= window.delivery_end
        and (window.settlement_period is None or row.settlement_period == window.settlement_period)
    ]


def _summary_for(settings: Settings, window: ResolvedWindow, rows: list[IntervalScore]):
    return summarise_scored_intervals(
        rows,
        timezone_name=settings.decision_timezone,
        cutoff_local=window.decision_cutoff_local,
        denominator_definition=REQUESTED_WINDOW_DENOMINATOR,
    )


def _score_block(
    *,
    role: ComparisonRole,
    available_to_purchaser: bool,
    description: str,
    summary,
) -> ScoreBlock:
    return ScoreBlock(
        role=role,
        available_to_purchaser=available_to_purchaser,
        description=description,
        metrics=summary.metrics,
        coverage=summary.coverage,
        distinct_selected_publish_times_utc=summary.distinct_selected_publish_times_utc,
        selections_after_cutoff=summary.selections_after_cutoff,
    )


def _series_interval(row: IntervalScore) -> SeriesInterval:
    return SeriesInterval(
        start_time_utc=row.start_time_utc,
        delivery_date=row.delivery_date,
        settlement_period=row.settlement_period,
        local_start_time=row.local_start_time,
        cutoff_utc=row.cutoff_utc,
        actual_generation_mw=row.actual_generation_mw,
        actual_measurement="measured" if row.actual_generation_mw is not None else "missing",
        selected_publish_time_utc=row.selected_publish_time_utc,
        forecast_generation_mw=row.forecast_generation_mw,
        forecast_measurement="measured" if row.forecast_generation_mw is not None else "missing",
        signed_error_mw=row.signed_error_mw,
        absolute_error_mw=row.absolute_error_mw,
        match_status=row.match_status,
    )


def _requested_window(settings: Settings, window: ResolvedWindow) -> RequestedWindow:
    return RequestedWindow(
        delivery_start=window.delivery_start,
        delivery_end=window.delivery_end,
        decision_timezone=settings.decision_timezone,
        decision_cutoff_local=window.decision_cutoff_local,
        cutoff_basis=PILOT_CUTOFF_BASIS,
        cutoff_convention=CUTOFF_CONVENTION,
        settlement_period=window.settlement_period,
        generation_unit=GENERATION_UNIT,
        error_unit=ERROR_UNIT,
    )


def _provenance(settings: Settings, prepared: PreparedStudy) -> SourceProvenance:
    report = prepared.report
    return SourceProvenance(
        fetched_at_utc=prepared.extract.fetched_at_utc,
        data_attribution=report.attribution or BMRS_DATA_ATTRIBUTION,
        data_licence_url=report.data_licence_url or BMRS_DATA_LICENCE_URL,
        ingestion_coverage_status=report.coverage_status,
        ingestion_limitations=report.coverage_limitations,
        cache_actual_rows=len(prepared.extract.actuals),
        cache_forecast_rows=len(prepared.extract.forecasts),
        study_window_matches_request_settings=(
            report.study_start == settings.study_start and report.study_end == settings.study_end
        ),
    )


def _examples(values: list[str]) -> ExampleList:
    return ExampleList(count=len(values), examples=values[:20])


def _reject_leaked_primary(selections_after_cutoff: int) -> None:
    if selections_after_cutoff != 0:
        raise RuntimeError(
            "A forecast published after the cutoff entered the primary comparison."
        )
