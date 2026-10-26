"""Ingestion tests use labelled synthetic responses and never call Elexon."""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.data_access.errors import ElexonTransportError
from app.data_access.ingestion import ingest_study_window
from app.settings import Settings

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "synthetic_stream_responses.json"
RECORDED_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "recorded_stream_excerpt.json"
SYNTHETIC_LABEL = "synthetic"


def test_labelled_synthetic_fixture_keeps_both_forecast_vintages(tmp_path: Path) -> None:
    fixture_document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture_document["fixture_label"] == SYNTHETIC_LABEL
    assert "not Elexon" in fixture_document["warning"]
    fetcher = QueueFetcher(
        {
            "/datasets/FUELHH/stream": fixture_document["fuelhh_rows"],
            "/datasets/WINDFOR/stream": fixture_document["windfor_rows"],
        }
    )

    report = ingest_study_window(
        _one_day_settings(tmp_path),
        json_array_fetcher=fetcher,
        fetched_at_utc=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )

    assert report.evaluation_status == "not_calculated"
    assert report.actuals.records_received == 2
    assert report.actuals.records_retained == 1
    assert report.actuals.duplicates.identical_copies_collapsed == 1
    assert report.forecasts.records_retained == 2
    assert report.forecasts.vintage_count == 2
    assert report.coverage_status == "incomplete"
    assert report.actuals.missing_half_hour_start_times_utc


def test_recorded_excerpt_parses_without_calling_elexon() -> None:
    fixture_document = json.loads(RECORDED_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture_document["fixture_label"] == "recorded"
    assert "live Elexon" in fixture_document["warning"]
    from app.data_access.record_parsing import parse_actual_rows, parse_forecast_rows

    parsed_actuals = parse_actual_rows(fixture_document["fuelhh_rows"])
    parsed_forecasts = parse_forecast_rows(fixture_document["windfor_rows"])

    assert parsed_actuals.malformed_reasons == []
    assert len(parsed_actuals.records) == 1
    assert parsed_actuals.records[0].generation_mw == 13756
    assert len(parsed_forecasts.records) == 2
    assert parsed_forecasts.records[0].start_time_utc == parsed_forecasts.records[1].start_time_utc
    assert parsed_forecasts.records[0].publish_time_utc != parsed_forecasts.records[1].publish_time_utc


def test_complete_synthetic_day_retains_separate_vintages_and_drops_nothing_conflicting(
    tmp_path: Path,
) -> None:
    actual_rows = synthetic_actual_day(date(2026, 1, 1))
    actual_rows.append(dict(actual_rows[0]))
    forecast_rows = synthetic_hourly_vintage("2025-12-31T07:30:00Z", date(2026, 1, 1), generation_mw=900)
    forecast_rows.extend(
        synthetic_hourly_vintage("2025-12-31T09:30:00Z", date(2026, 1, 1), generation_mw=950)
    )
    forecast_rows.append(
        {
            "dataset": "WINDFOR",
            "publishTime": "2025-12-31T07:30:00Z",
            "startTime": "2025-12-31T21:00:00Z",
            "generation": 800,
        }
    )
    fetcher = QueueFetcher(
        {
            "/datasets/FUELHH/stream": actual_rows,
            "/datasets/WINDFOR/stream": forecast_rows,
        }
    )

    report = ingest_study_window(_one_day_settings(tmp_path), json_array_fetcher=fetcher)

    assert report.coverage_status == "complete"
    assert report.actuals.records_received == 49
    assert report.actuals.records_retained == 48
    assert report.actuals.duplicates.identical_copies_collapsed == 1
    assert report.forecasts.records_received == 49
    assert report.forecasts.records_outside_study_window == 1
    assert report.forecasts.records_retained == 48
    assert report.forecasts.vintage_count == 2
    assert report.forecasts.observed_start_time_spacings_minutes == [60]
    assert report.actuals.target_timestamps.minimum_utc == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert report.actuals.target_timestamps.maximum_utc == datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)
    assert report.forecasts.publication_timestamps.minimum_utc == datetime(2025, 12, 31, 7, 30, tzinfo=timezone.utc)
    assert report.forecasts.publication_timestamps.maximum_utc == datetime(2025, 12, 31, 9, 30, tzinfo=timezone.utc)
    cached_forecast_count = _cached_row_count(tmp_path / "cache.sqlite", "wind_forecasts")
    assert cached_forecast_count == 48


def test_conflicting_duplicate_is_retained_and_counted(tmp_path: Path) -> None:
    actual_rows = synthetic_actual_day(date(2026, 1, 1))
    conflicting_copy = dict(actual_rows[0])
    conflicting_copy["generation"] = 5
    actual_rows.append(conflicting_copy)
    fetcher = QueueFetcher(
        {
            "/datasets/FUELHH/stream": actual_rows,
            "/datasets/WINDFOR/stream": synthetic_hourly_vintage(
                "2025-12-31T07:30:00Z",
                date(2026, 1, 1),
                generation_mw=900,
            ),
        }
    )

    report = ingest_study_window(_one_day_settings(tmp_path), json_array_fetcher=fetcher)

    assert report.actuals.duplicates.conflicting_key_groups == 1
    assert report.actuals.duplicates.conflicting_records_retained == 2
    assert report.actuals.records_retained == 49
    assert report.coverage_status == "incomplete"
    assert _cached_row_count(tmp_path / "cache.sqlite", "wind_actuals") == 49


def test_malformed_null_and_negative_generation_are_reported(tmp_path: Path) -> None:
    actual_rows = synthetic_actual_day(date(2026, 1, 1))
    actual_rows[1]["generation"] = None
    actual_rows[2]["generation"] = -4
    actual_rows.append(
        {
            "dataset": "FUELHH",
            "publishTime": "2026-01-01T02:00:00Z",
            "startTime": "2026-01-01T01:00:00",
            "settlementDate": "2026-01-01",
            "settlementPeriod": 3,
            "fuelType": "WIND",
            "generation": 1,
        }
    )
    actual_rows.append(
        {
            "dataset": "FUELHH",
            "publishTime": "2026-01-01T02:00:00Z",
            "startTime": "2026-01-01T01:00:00Z",
            "settlementDate": "2026-01-01",
            "settlementPeriod": 3,
            "fuelType": "CCGT",
            "generation": 1,
        }
    )
    fetcher = QueueFetcher(
        {
            "/datasets/FUELHH/stream": actual_rows,
            "/datasets/WINDFOR/stream": synthetic_hourly_vintage(
                "2025-12-31T07:30:00Z",
                date(2026, 1, 1),
                generation_mw=900,
            ),
        }
    )

    report = ingest_study_window(_one_day_settings(tmp_path), json_array_fetcher=fetcher)

    assert report.actuals.generation.missing_generation_records == 1
    assert report.actuals.generation.negative_generation_records == 1
    assert report.actuals.malformed_records == 1
    assert report.actuals.excluded_non_wind_records == 1
    assert any("timezone" in example for example in report.actuals.malformed_examples)
    assert report.coverage_status == "incomplete"
    assert _cached_row_count(tmp_path / "cache.sqlite", "rejected_stream_rows") == 1


def test_empty_stream_does_not_invent_rows(tmp_path: Path) -> None:
    fetcher = QueueFetcher(
        {
            "/datasets/FUELHH/stream": [],
            "/datasets/WINDFOR/stream": [],
        }
    )

    report = ingest_study_window(_one_day_settings(tmp_path), json_array_fetcher=fetcher)

    assert report.actuals.records_received == 0
    assert report.actuals.records_retained == 0
    assert report.forecasts.records_retained == 0
    assert report.coverage_status == "incomplete"
    assert _cached_row_count(tmp_path / "cache.sqlite", "wind_actuals") == 0


def test_rerun_replaces_the_cache_instead_of_appending(tmp_path: Path) -> None:
    fetcher = QueueFetcher(
        {
            "/datasets/FUELHH/stream": synthetic_actual_day(date(2026, 1, 1)),
            "/datasets/WINDFOR/stream": synthetic_hourly_vintage(
                "2025-12-31T07:30:00Z",
                date(2026, 1, 1),
                generation_mw=900,
            ),
        }
    )
    settings = _one_day_settings(tmp_path)

    ingest_study_window(settings, json_array_fetcher=fetcher)
    ingest_study_window(settings, json_array_fetcher=fetcher)

    assert _cached_row_count(tmp_path / "cache.sqlite", "wind_actuals") == 48
    assert _cached_row_count(tmp_path / "cache.sqlite", "ingestion_runs") == 1


def test_full_window_transport_failure_chunks_and_still_uses_only_fetcher_rows(tmp_path: Path) -> None:
    fetcher = ChunkingFetcher()
    settings = Settings(
        study_start="2026-01-01",
        study_end="2026-01-08",
        cache_path=str(tmp_path / "cache.sqlite"),
    )

    report = ingest_study_window(settings, json_array_fetcher=fetcher)

    assert report.request_strategy == "chunked_after_failure"
    assert report.actuals.records_retained == 8 * 48
    assert fetcher.full_window_attempts == 1
    assert fetcher.chunk_attempts == 2


def test_repeated_chunk_boundary_forecast_is_collapsed(tmp_path: Path) -> None:
    actual_rows = synthetic_actual_day(date(2026, 1, 1))
    repeated_forecast = {
        "dataset": "WINDFOR",
        "publishTime": "2025-12-31T07:30:00Z",
        "startTime": "2026-01-01T00:00:00Z",
        "generation": 900,
    }
    fetcher = QueueFetcher(
        {
            "/datasets/FUELHH/stream": actual_rows,
            "/datasets/WINDFOR/stream": [repeated_forecast, dict(repeated_forecast)],
        }
    )

    report = ingest_study_window(_one_day_settings(tmp_path), json_array_fetcher=fetcher)

    assert report.forecasts.records_received == 2
    assert report.forecasts.records_retained == 1
    assert report.forecasts.duplicates.identical_copies_collapsed == 1


class QueueFetcher:
    """Returns a prepared synthetic payload for each stream path."""

    def __init__(self, payloads_by_path_suffix: dict[str, list[object]]) -> None:
        self.payloads_by_path_suffix = payloads_by_path_suffix

    def fetch_json_array(
        self,
        request_url: str,
        query_parameters: dict[str, str],
    ) -> list[object]:
        del query_parameters
        for path_suffix, payload in self.payloads_by_path_suffix.items():
            if request_url.endswith(path_suffix):
                return payload
        raise AssertionError(f"Unexpected URL in a synthetic test: {request_url}")


class ChunkingFetcher:
    """Fails the wide synthetic query, then returns rows for the smaller chunks."""

    def __init__(self) -> None:
        self.full_window_attempts = 0
        self.chunk_attempts = 0

    def fetch_json_array(
        self,
        request_url: str,
        query_parameters: dict[str, str],
    ) -> list[object]:
        if request_url.endswith("/datasets/WINDFOR/stream"):
            return synthetic_hourly_vintage("2025-12-31T07:30:00Z", date(2026, 1, 1), generation_mw=900)
        settlement_from = date.fromisoformat(query_parameters["settlementDateFrom"])
        settlement_to = date.fromisoformat(query_parameters["settlementDateTo"])
        if (settlement_to - settlement_from).days > 6:
            self.full_window_attempts += 1
            raise ElexonTransportError("synthetic timeout for the full window")
        self.chunk_attempts += 1
        rows: list[object] = []
        settlement_date = settlement_from
        while settlement_date <= settlement_to:
            rows.extend(synthetic_actual_day(settlement_date))
            settlement_date += timedelta(days=1)
        return rows


def synthetic_actual_day(settlement_date: date) -> list[dict[str, object]]:
    """Build 48 labelled synthetic half-hours. These are not measured values."""
    rows: list[dict[str, object]] = []
    for period_index in range(48):
        start_time = datetime(settlement_date.year, settlement_date.month, settlement_date.day, tzinfo=timezone.utc) + timedelta(
            minutes=30 * period_index
        )
        rows.append(
            {
                "dataset": "FUELHH",
                "publishTime": (start_time + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "settlementDate": settlement_date.isoformat(),
                "settlementPeriod": period_index + 1,
                "fuelType": "WIND",
                "generation": 1000 + period_index,
            }
        )
    return rows


def synthetic_hourly_vintage(
    publish_time_utc: str,
    settlement_date: date,
    generation_mw: int,
) -> list[dict[str, object]]:
    """Build 24 labelled synthetic hourly forecasts for one vintage."""
    rows: list[dict[str, object]] = []
    for hour_index in range(24):
        start_time = datetime(
            settlement_date.year,
            settlement_date.month,
            settlement_date.day,
            hour_index,
            tzinfo=timezone.utc,
        )
        rows.append(
            {
                "dataset": "WINDFOR",
                "publishTime": publish_time_utc,
                "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "generation": generation_mw,
            }
        )
    return rows


def _one_day_settings(tmp_path: Path) -> Settings:
    return Settings(
        study_start="2026-01-01",
        study_end="2026-01-01",
        cache_path=str(tmp_path / "cache.sqlite"),
        forecast_publish_lookback_days=3,
        forecast_publish_lookahead_days=3,
    )


def _cached_row_count(cache_path: Path, table_name: str) -> int:
    connection = sqlite3.connect(cache_path)
    try:
        count_row = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    finally:
        connection.close()
    assert count_row is not None
    return int(count_row[0])
