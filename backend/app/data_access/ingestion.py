"""Fetch the January study extract and cache it with a quality report.

Forecast-error scoring is intentionally not done here.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.attribution import BMRS_DATA_ATTRIBUTION, BMRS_DATA_LICENCE_URL
from app.data_access.coverage import (
    actual_timestamp_quality,
    count_generation_problems,
    forecast_spacing_summary,
)
from app.data_access.deduplication import DEDUPLICATION_POLICY, deduplicate_records
from app.data_access.elexon_stream_reader import ElexonStreamReader, JsonArrayFetcher
from app.data_access.errors import ElexonTransportError
from app.data_access.record_parsing import (
    WindActualRecord,
    WindForecastRecord,
    parse_actual_rows,
    parse_forecast_rows,
)
from app.data_access.retrying_http_client import RetryingHttpClient
from app.data_access.sqlite_cache import replace_study_cache
from app.data_access.stream_queries import FUELHH_STREAM_PATH, WINDFOR_STREAM_PATH, build_fuelhh_wind_query, build_windfor_query
from app.data_access.study_window import (
    forecast_publish_bounds,
    iter_publish_chunks,
    iter_settlement_chunks,
    study_target_bounds,
)
from app.data_access.timestamps import parse_utc_timestamp
from app.schemas.ingestion import (
    ActualIngestionQuality,
    DuplicateAccounting,
    ForecastIngestionQuality,
    GenerationQuality,
    IngestionReport,
    TimestampBounds,
)
from app.settings import Settings

logger = logging.getLogger("wind_procurement.ingestion")

PAGINATION_NOTE = (
    "The FUELHH and WINDFOR stream documentation lists no page, offset, limit, or cursor. "
    "A successful response is one JSON array. The client does not request another page and "
    "does not treat a short array as a truncated page."
)
RATE_LIMIT_NOTE = (
    "The Insights guidance states 5000 requests per minute. Ingestion uses one request per "
    "stream unless that request fails transport, in which case it uses weekly or daily chunks. "
    "HTTP 429, 500, 502, 503, and 504 are retried a bounded number of times."
)
MALFORMED_EXAMPLE_LIMIT = 8


def ingest_study_window(
    settings: Settings,
    json_array_fetcher: JsonArrayFetcher | None = None,
    fetched_at_utc: datetime | None = None,
) -> IngestionReport:
    """Download both streams, validate them, and replace the local cache."""
    owns_http_client = json_array_fetcher is None
    http_client = _build_http_client(settings) if json_array_fetcher is None else None
    fetcher = http_client if http_client is not None else json_array_fetcher
    assert fetcher is not None
    try:
        stream_reader = ElexonStreamReader(settings.elexon_base_url, fetcher)
        actual_rows, forecast_rows, request_strategy = _read_study_streams(stream_reader, settings)
        report, retained_actuals, retained_forecasts, rejected_reasons = _build_report(
            settings=settings,
            actual_rows=actual_rows,
            forecast_rows=forecast_rows,
            request_strategy=request_strategy,
            fetched_at_utc=fetched_at_utc or datetime.now(timezone.utc),
        )
        replace_study_cache(
            settings.resolved_cache_path,
            report,
            retained_actuals,
            retained_forecasts,
            rejected_reasons,
        )
        logger.info(
            "Cached %s FUELHH rows and %s WINDFOR rows. Coverage is %s. Forecast error was not calculated.",
            report.actuals.records_retained,
            report.forecasts.records_retained,
            report.coverage_status,
        )
        return report
    finally:
        if owns_http_client and http_client is not None:
            http_client.close()


def _build_http_client(settings: Settings) -> RetryingHttpClient:
    return RetryingHttpClient(
        connect_timeout_seconds=settings.http_connect_timeout_seconds,
        read_timeout_seconds=settings.http_read_timeout_seconds,
        max_attempts=settings.http_max_attempts,
        retry_backoff_seconds=settings.http_retry_backoff_seconds,
    )


def _read_study_streams(
    stream_reader: ElexonStreamReader,
    settings: Settings,
) -> tuple[list[object], list[object], str]:
    publish_from, publish_to = forecast_publish_bounds(
        settings.study_start,
        settings.study_end,
        settings.forecast_publish_lookback_days,
        settings.forecast_publish_lookahead_days,
    )
    actual_rows, actuals_were_chunked = _read_actuals(stream_reader, settings)
    forecast_rows, forecasts_were_chunked = _read_forecasts(
        stream_reader,
        publish_from,
        publish_to,
    )
    request_strategy = (
        "chunked_after_failure" if actuals_were_chunked or forecasts_were_chunked else "single_query"
    )
    return actual_rows, forecast_rows, request_strategy


def _read_actuals(
    stream_reader: ElexonStreamReader,
    settings: Settings,
) -> tuple[list[object], bool]:
    try:
        return (
            stream_reader.read_half_hourly_wind_actuals(settings.study_start, settings.study_end),
            False,
        )
    except ElexonTransportError as error:
        logger.warning(
            "The full FUELHH query failed after retries (%s). Retrying in weekly settlement chunks.",
            error,
        )
        combined_rows: list[object] = []
        for chunk_start, chunk_end in iter_settlement_chunks(settings.study_start, settings.study_end):
            combined_rows.extend(
                stream_reader.read_half_hourly_wind_actuals(chunk_start, chunk_end)
            )
        return combined_rows, True


def _read_forecasts(
    stream_reader: ElexonStreamReader,
    publish_from: datetime,
    publish_to: datetime,
) -> tuple[list[object], bool]:
    try:
        return stream_reader.read_wind_forecast_vintages(publish_from, publish_to), False
    except ElexonTransportError as error:
        logger.warning(
            "The full WINDFOR query failed after retries (%s). Retrying one publish day at a time.",
            error,
        )
        combined_rows: list[object] = []
        for chunk_start, chunk_end in iter_publish_chunks(publish_from, publish_to):
            combined_rows.extend(
                stream_reader.read_wind_forecast_vintages(chunk_start, chunk_end)
            )
        return combined_rows, True


def _build_report(
    settings: Settings,
    actual_rows: list[object],
    forecast_rows: list[object],
    request_strategy: str,
    fetched_at_utc: datetime,
) -> tuple[IngestionReport, list[WindActualRecord], list[WindForecastRecord], list[tuple[str, str]]]:
    parsed_actuals = parse_actual_rows(actual_rows)
    parsed_forecasts = parse_forecast_rows(forecast_rows)
    window_start, window_end = study_target_bounds(
        settings.study_start,
        settings.study_end,
        settings.decision_timezone,
    )
    forecasts_in_window: list[WindForecastRecord] = []
    forecasts_outside_window = 0
    for forecast_record in parsed_forecasts.records:
        target_start = parse_utc_timestamp(forecast_record.start_time_utc, "startTime")
        if window_start <= target_start < window_end:
            forecasts_in_window.append(forecast_record)
        else:
            forecasts_outside_window += 1

    actual_deduplication = deduplicate_records(
        parsed_actuals.records,
        natural_key_of=lambda record: record.natural_key,
        signature_of=lambda record: record.duplicate_signature(),
    )
    forecast_deduplication = deduplicate_records(
        forecasts_in_window,
        natural_key_of=lambda record: record.natural_key,
        signature_of=lambda record: record.duplicate_signature(),
    )
    retained_actuals = actual_deduplication.retained_records
    retained_forecasts = forecast_deduplication.retained_records
    missing_half_hours, unexpected_starts, period_mismatches = actual_timestamp_quality(
        retained_actuals,
        settings.study_start,
        settings.study_end,
        settings.decision_timezone,
    )
    forecast_spacings, uneven_vintages = forecast_spacing_summary(retained_forecasts)
    actual_missing, actual_negative = count_generation_problems(
        [record.generation_mw for record in retained_actuals]
    )
    forecast_missing, forecast_negative = count_generation_problems(
        [record.generation_mw for record in retained_forecasts]
    )
    actual_dataset_mismatches = sum(record.dataset != "FUELHH" for record in retained_actuals)
    forecast_dataset_mismatches = sum(record.dataset != "WINDFOR" for record in retained_forecasts)
    forecast_spans_study = _forecasts_span_study(
        retained_forecasts,
        settings.study_start,
        settings.study_end,
        settings.decision_timezone,
    )
    limitations, coverage_status = _coverage_decision(
        request_strategy=request_strategy,
        missing_half_hours=missing_half_hours,
        unexpected_starts=unexpected_starts,
        period_mismatches=period_mismatches,
        actual_malformed=len(parsed_actuals.malformed_reasons),
        forecast_malformed=len(parsed_forecasts.malformed_reasons),
        excluded_non_wind=parsed_actuals.excluded_non_wind_records,
        actual_missing=actual_missing,
        actual_negative=actual_negative,
        forecast_missing=forecast_missing,
        forecast_negative=forecast_negative,
        actual_conflicts=actual_deduplication.conflicting_key_groups,
        forecast_conflicts=forecast_deduplication.conflicting_key_groups,
        actual_dataset_mismatches=actual_dataset_mismatches,
        forecast_dataset_mismatches=forecast_dataset_mismatches,
        forecast_spans_study=forecast_spans_study,
        forecasts_retained=len(retained_forecasts),
    )
    publish_from, publish_to = forecast_publish_bounds(
        settings.study_start,
        settings.study_end,
        settings.forecast_publish_lookback_days,
        settings.forecast_publish_lookahead_days,
    )
    if request_strategy not in {"single_query", "chunked_after_failure"}:
        raise ValueError(f"Unknown request strategy {request_strategy!r}.")
    report = IngestionReport(
        fetched_at_utc=fetched_at_utc.astimezone(timezone.utc),
        elexon_base_url=settings.elexon_base_url,
        study_start=settings.study_start,
        study_end=settings.study_end,
        fuel_type="WIND",
        decision_timezone=settings.decision_timezone,
        actual_stream_path=FUELHH_STREAM_PATH,
        forecast_stream_path=WINDFOR_STREAM_PATH,
        actual_query=build_fuelhh_wind_query(settings.study_start, settings.study_end),
        forecast_query=build_windfor_query(publish_from, publish_to),
        request_strategy=request_strategy,
        pagination=PAGINATION_NOTE,
        rate_limit=RATE_LIMIT_NOTE,
        attribution=BMRS_DATA_ATTRIBUTION,
        data_licence_url=BMRS_DATA_LICENCE_URL,
        cache_path=settings.cache_path,
        coverage_status=coverage_status,
        coverage_limitations=limitations,
        evaluation_status="not_calculated",
        actuals=ActualIngestionQuality(
            records_received=len(actual_rows),
            malformed_records=len(parsed_actuals.malformed_reasons),
            records_parsed=len(parsed_actuals.records),
            records_retained=len(retained_actuals),
            excluded_non_wind_records=parsed_actuals.excluded_non_wind_records,
            target_timestamps=_bounds([record.start_time_utc for record in retained_actuals]),
            duplicates=DuplicateAccounting(
                natural_key="settlement_date, settlement_period, fuel_type",
                policy=DEDUPLICATION_POLICY,
                identical_copies_collapsed=actual_deduplication.identical_copies_collapsed,
                conflicting_key_groups=actual_deduplication.conflicting_key_groups,
                conflicting_records_retained=actual_deduplication.conflicting_records_retained,
            ),
            generation=GenerationQuality(
                missing_generation_records=actual_missing,
                negative_generation_records=actual_negative,
            ),
            missing_half_hour_start_times_utc=missing_half_hours,
            unexpected_start_times_utc=unexpected_starts,
            settlement_period_mismatches=period_mismatches,
            unexpected_dataset_records=actual_dataset_mismatches,
            malformed_examples=parsed_actuals.malformed_reasons[:MALFORMED_EXAMPLE_LIMIT],
        ),
        forecasts=ForecastIngestionQuality(
            records_received=len(forecast_rows),
            malformed_records=len(parsed_forecasts.malformed_reasons),
            records_parsed=len(parsed_forecasts.records),
            records_outside_study_window=forecasts_outside_window,
            records_retained=len(retained_forecasts),
            vintage_count=len({record.publish_time_utc for record in retained_forecasts}),
            target_timestamps=_bounds([record.start_time_utc for record in retained_forecasts]),
            publication_timestamps=_bounds([record.publish_time_utc for record in retained_forecasts]),
            duplicates=DuplicateAccounting(
                natural_key="publish_time_utc, start_time_utc",
                policy=DEDUPLICATION_POLICY,
                identical_copies_collapsed=forecast_deduplication.identical_copies_collapsed,
                conflicting_key_groups=forecast_deduplication.conflicting_key_groups,
                conflicting_records_retained=forecast_deduplication.conflicting_records_retained,
            ),
            generation=GenerationQuality(
                missing_generation_records=forecast_missing,
                negative_generation_records=forecast_negative,
            ),
            observed_start_time_spacings_minutes=forecast_spacings,
            vintages_with_uneven_spacing=uneven_vintages,
            unexpected_dataset_records=forecast_dataset_mismatches,
            malformed_examples=parsed_forecasts.malformed_reasons[:MALFORMED_EXAMPLE_LIMIT],
        ),
    )
    rejected_reasons = [
        ("FUELHH", reason) for reason in parsed_actuals.malformed_reasons
    ] + [
        ("WINDFOR", reason) for reason in parsed_forecasts.malformed_reasons
    ]
    return report, retained_actuals, retained_forecasts, rejected_reasons


def _bounds(timestamp_texts: list[str]) -> TimestampBounds:
    if not timestamp_texts:
        return TimestampBounds(minimum_utc=None, maximum_utc=None)
    ordered = sorted(parse_utc_timestamp(value, "timestamp") for value in timestamp_texts)
    return TimestampBounds(minimum_utc=ordered[0], maximum_utc=ordered[-1])


def _forecasts_span_study(
    retained_forecasts: list[WindForecastRecord],
    study_start: object,
    study_end: object,
    timezone_name: str,
) -> bool:
    from datetime import date
    from zoneinfo import ZoneInfo

    if not isinstance(study_start, date) or not isinstance(study_end, date) or not retained_forecasts:
        return False
    study_zone = ZoneInfo(timezone_name)
    local_dates = [
        parse_utc_timestamp(record.start_time_utc, "startTime").astimezone(study_zone).date()
        for record in retained_forecasts
    ]
    return min(local_dates) <= study_start and max(local_dates) >= study_end


def _coverage_decision(
    request_strategy: str,
    missing_half_hours: list[str],
    unexpected_starts: list[str],
    period_mismatches: int,
    actual_malformed: int,
    forecast_malformed: int,
    excluded_non_wind: int,
    actual_missing: int,
    actual_negative: int,
    forecast_missing: int,
    forecast_negative: int,
    actual_conflicts: int,
    forecast_conflicts: int,
    actual_dataset_mismatches: int,
    forecast_dataset_mismatches: int,
    forecast_spans_study: bool,
    forecasts_retained: int,
) -> tuple[list[str], str]:
    limitations = [
        PAGINATION_NOTE,
        RATE_LIMIT_NOTE,
        "WINDFOR rows are requested by publish time. Rows whose startTime is outside the study window are counted and are not retained. Separate publish times for the same startTime are kept.",
        "Forecast error is not calculated from this extract.",
    ]
    if request_strategy == "chunked_after_failure":
        limitations.append(
            "The full-window request failed transport checks, so the client used smaller chunks. "
            "Identical rows repeated on a chunk boundary are collapsed and counted."
        )
    problems: list[str] = []
    if missing_half_hours:
        problems.append(
            f"FUELHH is missing {len(missing_half_hours)} expected local half-hour starts."
        )
    if unexpected_starts:
        problems.append(
            f"FUELHH has {len(unexpected_starts)} startTime values off the local half-hour grid."
        )
    if period_mismatches:
        problems.append(
            f"{period_mismatches} FUELHH rows have a settlement period that does not match local midnight plus 30-minute steps."
        )
    if actual_malformed or forecast_malformed:
        problems.append(
            f"Malformed rows were rejected: {actual_malformed} FUELHH and {forecast_malformed} WINDFOR."
        )
    if excluded_non_wind:
        problems.append(f"{excluded_non_wind} FUELHH rows were not WIND and were excluded.")
    if actual_missing or forecast_missing:
        problems.append(
            f"Null generation values were retained and not treated as zero: {actual_missing} actual, {forecast_missing} forecast."
        )
    if actual_negative or forecast_negative:
        problems.append(
            f"Negative generation values were retained and flagged: {actual_negative} actual, {forecast_negative} forecast."
        )
    if actual_conflicts or forecast_conflicts:
        problems.append(
            f"Conflicting duplicate keys were retained: {actual_conflicts} actual groups and {forecast_conflicts} forecast groups."
        )
    if actual_dataset_mismatches or forecast_dataset_mismatches:
        problems.append(
            "Some retained rows did not use the expected dataset name "
            f"({actual_dataset_mismatches} not FUELHH, {forecast_dataset_mismatches} not WINDFOR)."
        )
    if forecasts_retained == 0 or not forecast_spans_study:
        problems.append(
            "Retained WINDFOR startTime values do not reach both the first and last study dates."
        )
    limitations.extend(problems)
    coverage_status = "incomplete" if problems else "complete"
    return limitations, coverage_status
