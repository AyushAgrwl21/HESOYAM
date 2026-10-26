"""API reads over a labelled synthetic cache, plus the local Elexon extract when present.

The rows built here are synthetic. They are not Elexon measurements.
No test calls Elexon.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.study_service import clear_prepared_studies
from app.data_access.errors import ElexonClientError
from app.data_access.record_parsing import WindActualRecord, WindForecastRecord
from app.data_access.sqlite_cache import replace_study_cache
from app.main import create_app
from app.schemas.ingestion import (
    ActualIngestionQuality,
    DuplicateAccounting,
    ForecastIngestionQuality,
    GenerationQuality,
    IngestionReport,
    TimestampBounds,
)
from app.settings import Settings

STUDY_DAY = date(2026, 1, 2)


@pytest.fixture(autouse=True)
def drop_scored_studies() -> None:
    clear_prepared_studies()
    yield
    clear_prepared_studies()


def test_summary_series_and_accuracy_agree_and_exclude_a_late_vintage(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    summary = client.get("/api/v1/summary")
    series = client.get("/api/v1/series")
    accuracy = client.get("/api/v1/accuracy")

    assert summary.status_code == 200
    assert series.status_code == 200
    assert accuracy.status_code == 200
    summary_body = summary.json()
    series_body = series.json()
    accuracy_body = accuracy.json()
    assert summary_body["trading_recommendation"] == "not_provided"
    assert summary_body["provenance"]["live_elexon_request"] is False
    assert summary_body["window"]["cutoff_basis"] == "pilot_assumption"
    assert summary_body["window"]["generation_unit"] == "MW"
    assert summary_body["window"]["metric_definitions"]["mape"] == "not_calculated"
    assert summary_body["primary"]["available_to_purchaser"] is True
    assert summary_body["latest_available"]["available_to_purchaser"] is False
    assert summary_body["primary"]["selections_after_cutoff"] == 0
    assert summary_body["primary"]["metrics"]["mean_absolute_error_mw"] == pytest.approx(2.5)
    assert summary_body["primary"]["metrics"]["mean_error_mw"] == pytest.approx(-0.5)
    assert summary_body["primary"]["metrics"]["weighted_absolute_percentage_error_percent"] == pytest.approx(
        100 * 5 / 30
    )
    assert summary_body["primary"]["metrics"] == accuracy_body["primary"]["metrics"]

    matched_errors = [
        interval["absolute_error_mw"]
        for interval in series_body["intervals"]
        if interval["match_status"] == "matched"
    ]
    assert matched_errors == [2, 3]
    assert sum(matched_errors) / len(matched_errors) == pytest.approx(
        summary_body["primary"]["metrics"]["mean_absolute_error_mw"]
    )
    assert 999 not in {interval["forecast_generation_mw"] for interval in series_body["intervals"]}
    midnight = _interval(series_body, "2026-01-02T00:00:00Z")
    half_past = _interval(series_body, "2026-01-02T00:30:00Z")
    assert midnight["forecast_generation_mw"] == 12
    assert midnight["selected_publish_time_utc"] == "2026-01-01T07:30:00Z"
    assert half_past["actual_generation_mw"] == 0
    assert half_past["actual_measurement"] == "measured"
    assert half_past["forecast_generation_mw"] is None
    assert half_past["forecast_measurement"] == "missing"
    assert half_past["signed_error_mw"] is None
    empty_period = _interval(series_body, "2026-01-02T03:00:00Z")
    assert empty_period["actual_generation_mw"] is None
    assert empty_period["actual_measurement"] == "missing"
    assert empty_period["forecast_measurement"] == "missing"

    later_cutoff = client.get("/api/v1/series", params={"decision_cutoff_local": "09:01"})
    assert later_cutoff.status_code == 200
    later_midnight = _interval(later_cutoff.json(), "2026-01-02T00:00:00Z")
    assert later_midnight["forecast_generation_mw"] == 999
    assert later_midnight["selected_publish_time_utc"] == "2026-01-01T09:00:01Z"


def test_invalid_query_parameters_are_rejected(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    reversed_dates = client.get("/api/v1/summary", params={"date_from": "2026-01-02", "date_to": "2026-01-01"})
    outside_study = client.get("/api/v1/summary", params={"delivery_date": "2026-02-01"})
    mixed_dates = client.get(
        "/api/v1/summary",
        params={"delivery_date": "2026-01-02", "date_from": "2026-01-02"},
    )
    bad_cutoff = client.get("/api/v1/accuracy", params={"decision_cutoff_local": "25:99"})
    bad_period = client.get("/api/v1/series", params={"settlement_period": 0})
    missing_target = client.get("/api/v1/forecast-vintages")

    for response in (reversed_dates, outside_study, mixed_dates, bad_cutoff, bad_period, missing_target):
        assert response.status_code == 422
        assert response.json()["error_code"] == "invalid_request"
        assert response.json()["detail"]


def test_missing_cache_is_not_an_empty_success(tmp_path: Path) -> None:
    cache_path = tmp_path / "missing.sqlite"
    client = TestClient(create_app(_settings(tmp_path, cache_path)))

    response = client.get("/api/v1/summary")

    assert response.status_code == 409
    assert response.json()["error_code"] == "cache_missing"
    assert "empty" in response.json()["detail"]
    assert response.json().get("primary") is None
    assert not cache_path.exists()


def test_upstream_failure_does_not_replace_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = _write_cache(tmp_path)
    modified_at = cache_path.stat().st_mtime_ns

    def fail_upstream(path: Path):
        del path
        raise ElexonClientError("Elexon returned HTTP 503 for the test.")

    monkeypatch.setattr("app.api.study_service.load_cached_extract", fail_upstream)
    client = TestClient(create_app(_settings(tmp_path, cache_path)))

    response = client.get("/api/v1/data-quality")

    assert response.status_code == 502
    assert response.json()["error_code"] == "upstream_unavailable"
    assert "empty dataset" in response.json()["detail"]
    assert cache_path.stat().st_mtime_ns == modified_at
    assert cache_path.stat().st_size > 0


def test_vintages_keep_the_post_cutoff_publication_out_of_the_decision(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get(
        "/api/v1/forecast-vintages",
        params={"delivery_date": "2026-01-02", "settlement_period": 1},
    )

    assert response.status_code == 200
    evolution = response.json()["evolution"]
    assert evolution["target_start_time_utc"] == "2026-01-02T00:00:00Z"
    selected = [point for point in evolution["points"] if point["selected_for_decision"]]
    latest = [point for point in evolution["points"] if point["selected_for_latest_available"]]
    assert selected[0]["publish_time_utc"] == "2026-01-01T07:30:00Z"
    assert selected[0]["generation_mw"] == 12
    assert latest[0]["publish_time_utc"] == "2026-01-01T09:00:01Z"
    assert latest[0]["eligible_at_decision"] is False
    assert response.json()["primary_score_uses_only_eligible_points"] is True


def test_data_quality_reports_retrieval_separately_from_the_score(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/api/v1/data-quality", params={"delivery_date": "2026-01-02"})

    assert response.status_code == 200
    body = response.json()
    assert body["retrieval"]["coverage_status"] == "complete"
    assert body["retrieval"]["actual_rows_retained"] == 3
    assert body["requested_window_coverage"]["matched_interval_count"] == 2
    assert body["requested_window_coverage"]["status_counts"]["missing_forecast"] == 1
    assert body["scoring_duplicates"]["conflicting_forecast_keys"] == 0


def test_openapi_lists_the_read_routes() -> None:
    client = TestClient(create_app(Settings(cache_path="data/not-used-for-openapi.sqlite")))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/summary" in paths
    assert "/api/v1/series" in paths
    assert "/api/v1/accuracy" in paths
    assert "/api/v1/forecast-vintages" in paths
    assert "/api/v1/data-quality" in paths


def test_real_january_cache_summary_when_the_extract_is_present() -> None:
    cache_path = Path("data/wind_procurement.sqlite")
    if not cache_path.is_file():
        pytest.skip("The local Elexon cache is not present.")
    client = TestClient(create_app(Settings(cache_path=str(cache_path))))

    summary = client.get("/api/v1/summary")
    series = client.get("/api/v1/series", params={"delivery_date": "2026-01-01"})
    accuracy = client.get("/api/v1/accuracy", params={"delivery_date": "2026-01-01"})
    vintages = client.get(
        "/api/v1/forecast-vintages",
        params={"delivery_date": "2026-01-01", "settlement_period": 1},
    )
    quality = client.get("/api/v1/data-quality")

    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["provenance"]["fetched_at_utc"] == "2026-10-25T21:23:43Z"
    assert summary_body["provenance"]["live_elexon_request"] is False
    assert summary_body["provenance"]["ingestion_coverage_status"] == "complete"
    assert summary_body["primary"]["metrics"]["matched_interval_count"] == 744
    assert summary_body["primary"]["coverage"]["denominator_interval_count"] == 1488
    assert summary_body["primary"]["metrics"]["mean_absolute_error_mw"] == pytest.approx(2127.4825268817203)
    assert summary_body["primary"]["selections_after_cutoff"] == 0
    assert summary_body["latest_available"]["available_to_purchaser"] is False
    assert vintages.status_code == 200
    selected = [
        point
        for point in vintages.json()["evolution"]["points"]
        if point["selected_for_decision"]
    ]
    assert selected[0]["publish_time_utc"] == "2025-12-31T07:30:00Z"
    assert selected[0]["generation_mw"] == 19412
    assert series.status_code == 200
    january_first = series.json()
    assert january_first["interval_count"] == 48
    assert january_first["truncated"] is False
    matched_on_day = [
        interval for interval in january_first["intervals"] if interval["match_status"] == "matched"
    ]
    assert len(matched_on_day) == 24
    half_hour = next(
        interval for interval in january_first["intervals"] if interval["local_start_time"] == "00:30"
    )
    assert half_hour["forecast_measurement"] == "missing"
    assert half_hour["actual_measurement"] == "measured"
    assert half_hour["actual_generation_mw"] != 0
    assert accuracy.status_code == 200
    assert accuracy.json()["primary"]["metrics"]["matched_interval_count"] == 24
    assert accuracy.json()["by_delivery_day"][0]["delivery_date"] == "2026-01-01"
    assert quality.status_code == 200
    assert quality.json()["retrieval"]["coverage_status"] == "complete"
    assert quality.json()["retrieval"]["missing_half_hour_starts"]["count"] == 0


def _settings(tmp_path: Path, cache_path: Path | None = None) -> Settings:
    return Settings(
        study_start=STUDY_DAY,
        study_end=STUDY_DAY,
        cache_path=str(cache_path or _write_cache(tmp_path)),
        cors_allowed_origins="http://localhost:5173",
    )


def _write_cache(tmp_path: Path) -> Path:
    cache_path = tmp_path / "synthetic.sqlite"
    actuals = [
        _actual("2026-01-02T00:00:00Z", 1, 10),
        _actual("2026-01-02T00:30:00Z", 2, 0),
        _actual("2026-01-02T01:00:00Z", 3, 20),
    ]
    forecasts = [
        _forecast("2026-01-01T04:30:00Z", "2026-01-02T00:00:00Z", 1),
        _forecast("2026-01-01T07:30:00Z", "2026-01-02T00:00:00Z", 12),
        _forecast("2026-01-01T07:30:00Z", "2026-01-02T01:00:00Z", 17),
        _forecast("2026-01-01T09:00:01Z", "2026-01-02T00:00:00Z", 999),
    ]
    replace_study_cache(cache_path, _ingestion_report(cache_path, len(actuals), len(forecasts)), actuals, forecasts, [])
    return cache_path


def _actual(start_time_utc: str, settlement_period: int, generation_mw: int) -> WindActualRecord:
    return WindActualRecord(
        dataset="FUELHH",
        publish_time_utc="2026-01-02T12:00:00Z",
        start_time_utc=start_time_utc,
        settlement_date=STUDY_DAY,
        settlement_period=settlement_period,
        fuel_type="WIND",
        generation_mw=generation_mw,
    )


def _forecast(publish_time_utc: str, start_time_utc: str, generation_mw: int) -> WindForecastRecord:
    return WindForecastRecord(
        dataset="WINDFOR",
        publish_time_utc=publish_time_utc,
        start_time_utc=start_time_utc,
        generation_mw=generation_mw,
    )


def _ingestion_report(cache_path: Path, actual_rows: int, forecast_rows: int) -> IngestionReport:
    bounds = TimestampBounds(minimum_utc=None, maximum_utc=None)
    duplicates = DuplicateAccounting(
        natural_key="synthetic test key",
        policy="Synthetic rows for the API test. Not an Elexon measurement.",
        identical_copies_collapsed=0,
        conflicting_key_groups=0,
        conflicting_records_retained=0,
    )
    generation = GenerationQuality(missing_generation_records=0, negative_generation_records=0)
    return IngestionReport(
        fetched_at_utc=datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc),
        elexon_base_url="https://data.elexon.co.uk/bmrs/api/v1",
        study_start=STUDY_DAY,
        study_end=STUDY_DAY,
        fuel_type="WIND",
        decision_timezone="Europe/London",
        actual_stream_path="/datasets/FUELHH/stream",
        forecast_stream_path="/datasets/WINDFOR/stream",
        actual_query={"settlementDateFrom": "2026-01-02", "settlementDateTo": "2026-01-02", "fuelType": "WIND"},
        forecast_query={"publishDateTimeFrom": "2026-01-01T00:00:00Z", "publishDateTimeTo": "2026-01-03T00:00:00Z"},
        request_strategy="single_query",
        pagination="The stream response is one JSON array. This test cache was not fetched.",
        rate_limit="Not called.",
        attribution="Synthetic test cache. Not BMRS data.",
        data_licence_url="https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/",
        cache_path=str(cache_path),
        coverage_status="complete",
        coverage_limitations=[],
        evaluation_status="not_calculated",
        actuals=ActualIngestionQuality(
            records_received=actual_rows,
            malformed_records=0,
            records_parsed=actual_rows,
            records_retained=actual_rows,
            excluded_non_wind_records=0,
            target_timestamps=bounds,
            duplicates=duplicates,
            generation=generation,
            missing_half_hour_start_times_utc=[],
            unexpected_start_times_utc=[],
            settlement_period_mismatches=0,
            unexpected_dataset_records=0,
            malformed_examples=[],
        ),
        forecasts=ForecastIngestionQuality(
            records_received=forecast_rows,
            malformed_records=0,
            records_parsed=forecast_rows,
            records_outside_study_window=0,
            records_retained=forecast_rows,
            vintage_count=3,
            target_timestamps=bounds,
            publication_timestamps=bounds,
            duplicates=duplicates,
            generation=generation,
            observed_start_time_spacings_minutes=[60],
            vintages_with_uneven_spacing=0,
            unexpected_dataset_records=0,
            malformed_examples=[],
        ),
    )


def _interval(series_body: dict[str, object], start_time_utc: str) -> dict[str, object]:
    intervals = series_body["intervals"]
    assert isinstance(intervals, list)
    matches = [interval for interval in intervals if interval["start_time_utc"] == start_time_utc]
    assert len(matches) == 1
    return matches[0]
