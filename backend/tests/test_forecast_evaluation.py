"""Hand-calculated decision-time cases.

Rows built in this module are synthetic. They are not Elexon measurements.
The recorded fixture is the only input copied from a cached Elexon response.
No test calls Elexon.
"""

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.analytics.cutoff_policy import decision_cutoff_utc
from app.analytics.error_metrics import calculate_error_metrics
from app.analytics.forecast_evaluation import evaluate_decision_time_forecast
from app.data_access.record_parsing import (
    WindActualRecord,
    WindForecastRecord,
    parse_actual_rows,
    parse_forecast_rows,
)
from app.data_access.timestamps import parse_utc_timestamp
from app.schemas.evaluation import DecisionEvaluation, IntervalScore

RECORDED_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "recorded_decision_excerpt.json"
LONDON = "Europe/London"


def synthetic_actual(
    start_time_utc: str,
    settlement_period: int,
    generation_mw: int | None,
    *,
    settlement_date: str,
) -> WindActualRecord:
    """Build one labelled synthetic FUELHH row."""
    return WindActualRecord(
        dataset="FUELHH",
        publish_time_utc="2026-01-02T12:00:00Z",
        start_time_utc=start_time_utc,
        settlement_date=date.fromisoformat(settlement_date),
        settlement_period=settlement_period,
        fuel_type="WIND",
        generation_mw=generation_mw,
    )


def synthetic_forecast(
    publish_time_utc: str,
    start_time_utc: str,
    generation_mw: int | None,
) -> WindForecastRecord:
    """Build one labelled synthetic WINDFOR row."""
    return WindForecastRecord(
        dataset="WINDFOR",
        publish_time_utc=publish_time_utc,
        start_time_utc=start_time_utc,
        generation_mw=generation_mw,
    )


def primary_row(evaluation: DecisionEvaluation, start_time_utc: str) -> IntervalScore:
    matches = [row for row in evaluation.primary.series if row.start_time_utc == start_time_utc]
    assert len(matches) == 1
    return matches[0]


def latest_row(evaluation: DecisionEvaluation, start_time_utc: str) -> IntervalScore:
    matches = [
        row for row in evaluation.latest_available.series if row.start_time_utc == start_time_utc
    ]
    assert len(matches) == 1
    return matches[0]


def assert_primary_has_no_future_publication(evaluation: DecisionEvaluation) -> None:
    """Fail when any selected primary vintage was published after its cutoff."""
    assert evaluation.primary.selections_after_cutoff == 0
    assert evaluation.primary.available_to_purchaser is True
    assert evaluation.latest_available.available_to_purchaser is False
    assert evaluation.cutoff_basis == "pilot_assumption"
    for row in evaluation.primary.series:
        if row.selected_publish_time_utc is None:
            continue
        selected_publish_time = parse_utc_timestamp(row.selected_publish_time_utc, "publishTime")
        assert selected_publish_time <= row.cutoff_utc


def test_error_metrics_match_a_two_pair_hand_calculation() -> None:
    # Forecasts 12 and 17 MW. Actuals 10 and 20 MW.
    # Signed errors: +2 and -3. Absolute errors: 2 and 3.
    # Bias = (2 - 3) / 2 = -0.5
    # MAE = (2 + 3) / 2 = 2.5
    # RMSE = sqrt((4 + 9) / 2) = sqrt(6.5)
    # WAPE = 100 * (2 + 3) / (10 + 20) = 50 / 3
    metrics = calculate_error_metrics([(12, 10), (17, 20)])

    assert metrics.matched_interval_count == 2
    assert metrics.mean_error_mw == pytest.approx(-0.5)
    assert metrics.mean_absolute_error_mw == pytest.approx(2.5)
    assert metrics.root_mean_squared_error_mw == pytest.approx(math.sqrt(6.5))
    assert metrics.weighted_absolute_percentage_error_percent == pytest.approx(100 * 5 / 30)
    assert metrics.wape_status == "calculated"
    assert metrics.generation_unit == "MW"
    assert metrics.error_unit == "MW"
    assert "mape" not in metrics.model_dump()


def test_wape_is_undefined_when_the_actual_sum_is_not_positive() -> None:
    zeros = calculate_error_metrics([(4, 0), (6, 0)])
    assert zeros.mean_absolute_error_mw == pytest.approx(5)
    assert zeros.mean_error_mw == pytest.approx(5)
    assert zeros.root_mean_squared_error_mw == pytest.approx(math.sqrt(26))
    assert zeros.weighted_absolute_percentage_error_percent is None
    assert zeros.wape_status == "undefined_non_positive_actual_sum"

    negative_sum = calculate_error_metrics([(0, -5), (0, 0)])
    assert negative_sum.mean_absolute_error_mw == pytest.approx(2.5)
    assert negative_sum.weighted_absolute_percentage_error_percent is None
    assert negative_sum.wape_status == "undefined_non_positive_actual_sum"

    empty = calculate_error_metrics([])
    assert empty.mean_absolute_error_mw is None
    assert empty.mean_error_mw is None
    assert empty.root_mean_squared_error_mw is None
    assert empty.weighted_absolute_percentage_error_percent is None
    assert empty.wape_status == "not_applicable_no_matches"


def test_wape_stays_defined_when_one_matched_actual_is_zero() -> None:
    # Errors 0 and 10. Sum of actuals is 10, so WAPE is 100.
    metrics = calculate_error_metrics([(0, 0), (20, 10)])

    assert metrics.mean_absolute_error_mw == pytest.approx(5)
    assert metrics.mean_error_mw == pytest.approx(5)
    assert metrics.root_mean_squared_error_mw == pytest.approx(math.sqrt(50))
    assert metrics.weighted_absolute_percentage_error_percent == pytest.approx(100)
    assert metrics.wape_status == "calculated"


def test_latest_eligible_forecast_excludes_a_publication_one_second_late() -> None:
    evaluation = evaluate_decision_time_forecast(
        [
            synthetic_actual("2026-01-02T00:00:00Z", 1, 10, settlement_date="2026-01-02"),
            synthetic_actual("2026-01-02T00:30:00Z", 2, 0, settlement_date="2026-01-02"),
            synthetic_actual("2026-01-02T01:00:00Z", 3, 20, settlement_date="2026-01-02"),
        ],
        [
            synthetic_forecast("2026-01-01T04:30:00Z", "2026-01-02T00:00:00Z", 1),
            synthetic_forecast("2026-01-01T07:30:00Z", "2026-01-02T00:00:00Z", 12),
            synthetic_forecast("2026-01-01T07:30:00Z", "2026-01-02T01:00:00Z", 17),
            synthetic_forecast("2026-01-01T09:00:01Z", "2026-01-02T00:00:00Z", 999),
            synthetic_forecast("2026-01-01T07:30:00Z", "2026-01-02T02:00:00Z", 50),
        ],
        study_start=date(2026, 1, 2),
        study_end=date(2026, 1, 2),
        vintage_target_start_time_utc="2026-01-02T00:00:00Z",
    )

    assert_primary_has_no_future_publication(evaluation)
    midnight = primary_row(evaluation, "2026-01-02T00:00:00Z")
    half_past = primary_row(evaluation, "2026-01-02T00:30:00Z")
    one_oclock = primary_row(evaluation, "2026-01-02T01:00:00Z")
    two_oclock = primary_row(evaluation, "2026-01-02T02:00:00Z")

    assert midnight.cutoff_utc == datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    assert midnight.selected_publish_time_utc == "2026-01-01T07:30:00Z"
    assert midnight.forecast_generation_mw == 12
    assert midnight.actual_generation_mw == 10
    assert midnight.signed_error_mw == 2
    assert midnight.absolute_error_mw == 2
    assert midnight.match_status == "matched"
    assert one_oclock.forecast_generation_mw == 17
    assert one_oclock.signed_error_mw == -3
    assert one_oclock.absolute_error_mw == 3
    assert half_past.match_status == "missing_forecast"
    assert half_past.forecast_generation_mw is None
    assert half_past.signed_error_mw is None
    assert two_oclock.match_status == "missing_actual"
    assert two_oclock.actual_generation_mw is None
    assert two_oclock.forecast_generation_mw == 50
    assert two_oclock.signed_error_mw is None

    assert evaluation.primary.metrics.mean_absolute_error_mw == pytest.approx(2.5)
    assert evaluation.primary.metrics.mean_error_mw == pytest.approx(-0.5)
    assert evaluation.primary.metrics.root_mean_squared_error_mw == pytest.approx(math.sqrt(6.5))
    assert evaluation.primary.metrics.weighted_absolute_percentage_error_percent == pytest.approx(
        100 * 5 / 30
    )
    assert 999 not in {row.forecast_generation_mw for row in evaluation.primary.series}
    assert evaluation.primary.coverage.denominator_interval_count == 48
    assert evaluation.primary.coverage.matched_interval_count == 2
    assert evaluation.primary.coverage.status_counts.missing_forecast == 1
    assert evaluation.primary.coverage.status_counts.missing_actual == 1
    assert evaluation.primary.coverage.status_counts.missing_both == 44
    assert evaluation.primary.coverage.intervals_without_usable_forecast == 45
    assert evaluation.primary.coverage.intervals_without_usable_actual == 45
    assert evaluation.primary.coverage.coverage_percent == pytest.approx(100 * 2 / 48)

    period_one = next(
        item for item in evaluation.primary.by_settlement_period if item.settlement_period == 1
    )
    period_two = next(
        item for item in evaluation.primary.by_settlement_period if item.settlement_period == 2
    )
    assert period_one.local_start_time == "00:00"
    assert period_one.metrics.mean_absolute_error_mw == pytest.approx(2)
    assert period_two.metrics.matched_interval_count == 0
    assert period_two.metrics.mean_absolute_error_mw is None

    leaked = latest_row(evaluation, "2026-01-02T00:00:00Z")
    assert leaked.selected_publish_time_utc == "2026-01-01T09:00:01Z"
    assert leaked.forecast_generation_mw == 999
    assert leaked.signed_error_mw == 989
    assert evaluation.latest_available.metrics.mean_absolute_error_mw == pytest.approx(496)
    assert evaluation.latest_available.selections_after_cutoff == 1
    assert "not the decision-time score" in evaluation.latest_available.description

    assert evaluation.vintage_evolution is not None
    selected_points = [
        point for point in evaluation.vintage_evolution.points if point.selected_for_decision
    ]
    latest_points = [
        point
        for point in evaluation.vintage_evolution.points
        if point.selected_for_latest_available
    ]
    assert [point.publish_time_utc for point in selected_points] == ["2026-01-01T07:30:00Z"]
    assert [point.publish_time_utc for point in latest_points] == ["2026-01-01T09:00:01Z"]
    assert latest_points[0].eligible_at_decision is False
    assert selected_points[0].generation_mw == 12


def test_publication_at_the_exact_january_cutoff_is_selected() -> None:
    """09:00 Europe/London on 31 December 2025 is 09:00Z, and that instant is eligible."""
    evaluation = evaluate_decision_time_forecast(
        [synthetic_actual("2026-01-01T00:00:00Z", 1, 100, settlement_date="2026-01-01")],
        [
            synthetic_forecast("2025-12-31T07:30:00Z", "2026-01-01T00:00:00Z", 10),
            synthetic_forecast("2025-12-31T09:00:00Z", "2026-01-01T00:00:00Z", 40),
            synthetic_forecast("2025-12-31T09:00:01Z", "2026-01-01T00:00:00Z", 999),
        ],
        study_start=date(2026, 1, 1),
        study_end=date(2026, 1, 1),
    )

    assert_primary_has_no_future_publication(evaluation)
    midnight = primary_row(evaluation, "2026-01-01T00:00:00Z")
    assert midnight.cutoff_utc == datetime(2025, 12, 31, 9, 0, tzinfo=timezone.utc)
    assert midnight.selected_publish_time_utc == "2025-12-31T09:00:00Z"
    assert midnight.forecast_generation_mw == 40
    assert midnight.signed_error_mw == -60
    assert latest_row(evaluation, "2026-01-01T00:00:00Z").forecast_generation_mw == 999


def test_forecast_value_is_not_copied_onto_the_next_half_hour() -> None:
    evaluation = evaluate_decision_time_forecast(
        [
            synthetic_actual("2026-01-02T00:00:00Z", 1, 10, settlement_date="2026-01-02"),
            synthetic_actual("2026-01-02T01:00:00Z", 3, 20, settlement_date="2026-01-02"),
        ],
        [synthetic_forecast("2026-01-01T07:30:00Z", "2026-01-02T00:00:00Z", 12)],
        study_start=date(2026, 1, 2),
        study_end=date(2026, 1, 2),
    )

    assert_primary_has_no_future_publication(evaluation)
    assert primary_row(evaluation, "2026-01-02T01:00:00Z").match_status == "missing_forecast"
    assert primary_row(evaluation, "2026-01-02T01:00:00Z").forecast_generation_mw is None
    assert evaluation.primary.metrics.matched_interval_count == 1
    assert evaluation.primary.metrics.mean_absolute_error_mw == pytest.approx(2)


def test_identical_duplicate_is_counted_once() -> None:
    forecast = synthetic_forecast("2026-01-01T07:30:00Z", "2026-01-02T00:00:00Z", 15)
    evaluation = evaluate_decision_time_forecast(
        [synthetic_actual("2026-01-02T00:00:00Z", 1, 10, settlement_date="2026-01-02")],
        [forecast, forecast],
        study_start=date(2026, 1, 2),
        study_end=date(2026, 1, 2),
    )

    assert evaluation.inputs.duplicates.identical_forecast_copies_collapsed == 1
    assert evaluation.inputs.duplicates.conflicting_forecast_keys == 0
    midnight = primary_row(evaluation, "2026-01-02T00:00:00Z")
    assert midnight.match_status == "matched"
    assert midnight.forecast_generation_mw == 15
    assert midnight.signed_error_mw == 5
    assert evaluation.primary.metrics.matched_interval_count == 1


def test_conflicting_latest_vintage_is_excluded_and_not_replaced() -> None:
    evaluation = evaluate_decision_time_forecast(
        [synthetic_actual("2026-01-04T00:00:00Z", 1, 10, settlement_date="2026-01-04")],
        [
            synthetic_forecast("2026-01-03T04:30:00Z", "2026-01-04T00:00:00Z", 8),
            synthetic_forecast("2026-01-03T07:30:00Z", "2026-01-04T00:00:00Z", 10),
            synthetic_forecast("2026-01-03T07:30:00Z", "2026-01-04T00:00:00Z", 12),
        ],
        study_start=date(2026, 1, 4),
        study_end=date(2026, 1, 4),
        vintage_target_start_time_utc="2026-01-04T00:00:00Z",
    )

    midnight = primary_row(evaluation, "2026-01-04T00:00:00Z")
    assert midnight.match_status == "excluded_conflicting_forecast"
    assert midnight.selected_publish_time_utc == "2026-01-03T07:30:00Z"
    assert midnight.forecast_generation_mw is None
    assert midnight.signed_error_mw is None
    assert evaluation.primary.metrics.mean_absolute_error_mw is None
    assert evaluation.primary.metrics.matched_interval_count == 0
    assert evaluation.inputs.duplicates.conflicting_forecast_keys == 1
    assert evaluation.inputs.duplicates.conflicting_forecast_rows == 2
    assert 8 not in {row.forecast_generation_mw for row in evaluation.primary.series}
    assert evaluation.vintage_evolution is not None
    selected = next(
        point for point in evaluation.vintage_evolution.points if point.selected_for_decision
    )
    assert selected.publish_time_utc == "2026-01-03T07:30:00Z"
    assert selected.conflict is True
    assert selected.generation_mw is None


def test_null_latest_publication_is_a_gap_and_is_not_replaced() -> None:
    evaluation = evaluate_decision_time_forecast(
        [synthetic_actual("2026-01-04T00:00:00Z", 1, 10, settlement_date="2026-01-04")],
        [
            synthetic_forecast("2026-01-03T04:30:00Z", "2026-01-04T00:00:00Z", 8),
            synthetic_forecast("2026-01-03T07:30:00Z", "2026-01-04T00:00:00Z", None),
        ],
        study_start=date(2026, 1, 4),
        study_end=date(2026, 1, 4),
    )

    midnight = primary_row(evaluation, "2026-01-04T00:00:00Z")
    assert midnight.match_status == "missing_forecast"
    assert midnight.selected_publish_time_utc == "2026-01-03T07:30:00Z"
    assert midnight.forecast_generation_mw is None
    assert evaluation.primary.metrics.matched_interval_count == 0
    assert 8 not in {row.forecast_generation_mw for row in evaluation.primary.series}


def test_conflicting_actual_is_excluded_from_the_average() -> None:
    evaluation = evaluate_decision_time_forecast(
        [
            synthetic_actual("2026-01-04T00:00:00Z", 1, 1, settlement_date="2026-01-04"),
            synthetic_actual("2026-01-04T00:00:00Z", 1, 2, settlement_date="2026-01-04"),
        ],
        [synthetic_forecast("2026-01-03T07:30:00Z", "2026-01-04T00:00:00Z", 100)],
        study_start=date(2026, 1, 4),
        study_end=date(2026, 1, 4),
    )

    midnight = primary_row(evaluation, "2026-01-04T00:00:00Z")
    assert midnight.match_status == "excluded_conflicting_actual"
    assert midnight.actual_generation_mw is None
    assert midnight.signed_error_mw is None
    assert evaluation.primary.metrics.mean_error_mw is None
    assert evaluation.inputs.duplicates.conflicting_actual_keys == 1
    assert evaluation.inputs.duplicates.conflicting_actual_rows == 2


def test_timezone_boundary_uses_the_local_delivery_date() -> None:
    assert decision_cutoff_utc(date(2026, 1, 1), "09:00", LONDON) == datetime(
        2025, 12, 31, 9, 0, tzinfo=timezone.utc
    )
    assert decision_cutoff_utc(date(2026, 1, 31), "09:00", LONDON) == datetime(
        2026, 1, 30, 9, 0, tzinfo=timezone.utc
    )
    assert decision_cutoff_utc(date(2026, 6, 15), "09:00", LONDON) == datetime(
        2026, 6, 14, 8, 0, tzinfo=timezone.utc
    )
    assert decision_cutoff_utc(date(2026, 10, 25), "09:00", LONDON) == datetime(
        2026, 10, 24, 8, 0, tzinfo=timezone.utc
    )
    assert decision_cutoff_utc(date(2026, 10, 26), "09:00", LONDON) == datetime(
        2026, 10, 25, 9, 0, tzinfo=timezone.utc
    )

    june_fifteenth_start = "2026-06-14T23:00:00Z"
    june_fourteenth_start = "2026-06-13T23:00:00Z"
    evaluation = evaluate_decision_time_forecast(
        [
            synthetic_actual(june_fifteenth_start, 1, 100, settlement_date="2026-06-15"),
            synthetic_actual(june_fourteenth_start, 1, 10, settlement_date="2026-06-14"),
        ],
        [
            synthetic_forecast("2026-06-14T07:30:00Z", june_fifteenth_start, 40),
            synthetic_forecast("2026-06-14T08:00:00Z", june_fifteenth_start, 55),
            synthetic_forecast("2026-06-14T08:00:01Z", june_fifteenth_start, 900),
            synthetic_forecast("2026-06-14T07:30:00Z", june_fourteenth_start, 40),
        ],
        study_start=date(2026, 6, 14),
        study_end=date(2026, 6, 15),
        vintage_target_start_time_utc=june_fifteenth_start,
    )

    assert_primary_has_no_future_publication(evaluation)
    june_fifteenth = primary_row(evaluation, june_fifteenth_start)
    june_fourteenth = primary_row(evaluation, june_fourteenth_start)
    assert june_fifteenth.delivery_date == date(2026, 6, 15)
    assert june_fifteenth.cutoff_utc == datetime(2026, 6, 14, 8, 0, tzinfo=timezone.utc)
    assert june_fifteenth.selected_publish_time_utc == "2026-06-14T08:00:00Z"
    assert june_fifteenth.forecast_generation_mw == 55
    assert june_fifteenth.signed_error_mw == -45
    assert june_fourteenth.delivery_date == date(2026, 6, 14)
    assert june_fourteenth.match_status == "missing_forecast"
    assert june_fourteenth.forecast_generation_mw is None
    assert 900 not in {row.forecast_generation_mw for row in evaluation.primary.series}
    assert latest_row(evaluation, june_fifteenth_start).forecast_generation_mw == 900


def test_clock_change_days_change_the_coverage_denominator() -> None:
    short_day = evaluate_decision_time_forecast(
        [],
        [],
        study_start=date(2026, 3, 29),
        study_end=date(2026, 3, 29),
    )
    long_day = evaluate_decision_time_forecast(
        [],
        [],
        study_start=date(2026, 10, 25),
        study_end=date(2026, 10, 25),
    )

    assert short_day.primary.coverage.denominator_interval_count == 46
    assert long_day.primary.coverage.denominator_interval_count == 50
    short_local_times = [row.local_start_time for row in short_day.primary.series]
    long_local_times = [row.local_start_time for row in long_day.primary.series]
    assert "01:00" not in short_local_times
    assert short_local_times[2] == "02:00"
    assert long_local_times.count("01:00") == 2
    assert long_local_times.count("01:30") == 2
    assert short_day.primary.metrics.mean_absolute_error_mw is None
    assert long_day.primary.metrics.mean_absolute_error_mw is None
    assert {row.forecast_generation_mw for row in short_day.primary.series} == {None}
    assert {row.actual_generation_mw for row in long_day.primary.series} == {None}


def test_empty_january_reports_no_error_and_full_gap_coverage() -> None:
    evaluation = evaluate_decision_time_forecast(
        [],
        [],
        study_start=date(2026, 1, 1),
        study_end=date(2026, 1, 31),
    )

    denominator = evaluation.primary.coverage.denominator_interval_count
    assert denominator == 31 * 48
    assert evaluation.primary.coverage.matched_interval_count == 0
    assert evaluation.primary.coverage.coverage_percent == 0
    assert evaluation.primary.coverage.intervals_without_usable_forecast == denominator
    assert evaluation.primary.coverage.intervals_without_usable_actual == denominator
    assert evaluation.primary.coverage.status_counts.missing_both == denominator
    assert evaluation.primary.metrics.wape_status == "not_applicable_no_matches"
    assert evaluation.primary.metrics.mean_absolute_error_mw is None
    assert evaluation.latest_available.metrics.mean_absolute_error_mw is None
    assert len(evaluation.primary.by_delivery_day) == 31
    assert all(day.metrics.matched_interval_count == 0 for day in evaluation.primary.by_delivery_day)


def test_partial_month_leaves_the_uncovered_day_empty() -> None:
    evaluation = evaluate_decision_time_forecast(
        [synthetic_actual("2026-01-01T00:00:00Z", 1, 10, settlement_date="2026-01-01")],
        [synthetic_forecast("2025-12-31T07:30:00Z", "2026-01-01T00:00:00Z", 14)],
        study_start=date(2026, 1, 1),
        study_end=date(2026, 1, 2),
    )

    assert_primary_has_no_future_publication(evaluation)
    assert evaluation.primary.coverage.denominator_interval_count == 96
    assert evaluation.primary.coverage.matched_interval_count == 1
    assert evaluation.primary.metrics.mean_error_mw == pytest.approx(4)
    january_second = next(
        day for day in evaluation.primary.by_delivery_day if day.delivery_date == date(2026, 1, 2)
    )
    assert january_second.metrics.matched_interval_count == 0
    assert january_second.metrics.mean_absolute_error_mw is None
    assert january_second.coverage.status_counts.missing_both == 48
    assert january_second.selected_publish_times_utc == []
    january_second_rows = [
        row for row in evaluation.primary.series if row.delivery_date == date(2026, 1, 2)
    ]
    assert {row.forecast_generation_mw for row in january_second_rows} == {None}
    assert {row.actual_generation_mw for row in january_second_rows} == {None}


def test_misaligned_actual_is_not_moved_to_another_period() -> None:
    evaluation = evaluate_decision_time_forecast(
        [synthetic_actual("2026-01-02T00:00:00Z", 2, 80, settlement_date="2026-01-03")],
        [synthetic_forecast("2026-01-01T07:30:00Z", "2026-01-02T00:00:00Z", 10)],
        study_start=date(2026, 1, 2),
        study_end=date(2026, 1, 2),
    )

    midnight = primary_row(evaluation, "2026-01-02T00:00:00Z")
    assert evaluation.inputs.misaligned_actual_rows == 1
    assert midnight.actual_generation_mw is None
    assert midnight.match_status == "missing_actual"
    assert midnight.signed_error_mw is None
    assert 80 not in {row.actual_generation_mw for row in evaluation.primary.series}


def test_recorded_excerpt_selects_the_latest_publication_at_or_before_the_cutoff() -> None:
    fixture_document = json.loads(RECORDED_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture_document["fixture_label"] == "recorded"
    parsed_actuals = parse_actual_rows(fixture_document["fuelhh_rows"])
    parsed_forecasts = parse_forecast_rows(fixture_document["windfor_rows"])
    evaluation = evaluate_decision_time_forecast(
        parsed_actuals.records,
        parsed_forecasts.records,
        study_start=date(2026, 1, 1),
        study_end=date(2026, 1, 1),
        vintage_target_start_time_utc="2026-01-01T00:00:00Z",
    )

    assert_primary_has_no_future_publication(evaluation)
    # Recorded values: forecast 19412 MW, actual 13756 MW, signed error 5656 MW.
    # The 09:30Z publication is 19466 MW and is after 09:00Z on 31 December.
    midnight = primary_row(evaluation, "2026-01-01T00:00:00Z")
    half_past = primary_row(evaluation, "2026-01-01T00:30:00Z")
    assert midnight.selected_publish_time_utc == "2025-12-31T07:30:00Z"
    assert midnight.forecast_generation_mw == 19412
    assert midnight.actual_generation_mw == 13756
    assert midnight.signed_error_mw == 5656
    assert midnight.absolute_error_mw == 5656
    assert evaluation.primary.metrics.mean_absolute_error_mw == pytest.approx(5656)
    assert evaluation.primary.metrics.weighted_absolute_percentage_error_percent == pytest.approx(
        100 * 5656 / 13756
    )
    assert half_past.match_status == "missing_forecast"
    assert half_past.actual_generation_mw == 13873
    assert half_past.forecast_generation_mw is None
    assert latest_row(evaluation, "2026-01-01T00:00:00Z").forecast_generation_mw == 19466
    assert latest_row(evaluation, "2026-01-01T00:00:00Z").signed_error_mw == 5710
    assert evaluation.primary.metrics.mean_absolute_error_mw != pytest.approx(5710)
    assert evaluation.vintage_evolution is not None
    assert evaluation.vintage_evolution.points[1].publish_time_utc == "2025-12-31T07:30:00Z"
    assert evaluation.vintage_evolution.points[1].selected_for_decision is True
    assert evaluation.vintage_evolution.points[2].eligible_at_decision is False
