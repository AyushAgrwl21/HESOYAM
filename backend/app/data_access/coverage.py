"""Data-quality checks over retained rows. These checks do not call Elexon."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.data_access.record_parsing import WindActualRecord, WindForecastRecord
from app.data_access.study_window import expected_half_hour_starts
from app.data_access.timestamps import parse_utc_timestamp


def actual_timestamp_quality(
    retained_actuals: list[WindActualRecord],
    study_start_date: date,
    study_end_date: date,
    timezone_name: str,
) -> tuple[list[str], list[str], int]:
    """Return missing half-hours, unexpected starts, and settlement-period mismatches."""
    expected_starts = {
        start.strftime("%Y-%m-%dT%H:%M:%SZ")
        for start in expected_half_hour_starts(study_start_date, study_end_date, timezone_name)
    }
    observed_starts = {record.start_time_utc for record in retained_actuals}
    missing_starts = sorted(expected_starts - observed_starts)
    unexpected_starts = sorted(observed_starts - expected_starts)
    period_mismatches = sum(
        1
        for record in retained_actuals
        if not settlement_period_matches_start(record, timezone_name)
    )
    return missing_starts, unexpected_starts, period_mismatches


def settlement_period_matches_start(record: WindActualRecord, timezone_name: str) -> bool:
    """Compare period N with local midnight plus (N-1) elapsed half-hours.

    The addition is done in UTC so a short day skips the missing civil hour and
    a long day keeps both occurrences of the repeated hour.
    """
    study_zone = ZoneInfo(timezone_name)
    observed_start = parse_utc_timestamp(record.start_time_utc, "startTime")
    local_midnight = datetime.combine(
        record.settlement_date,
        datetime.min.time(),
        tzinfo=study_zone,
    )
    expected_start = local_midnight.astimezone(timezone.utc) + timedelta(
        minutes=30 * (record.settlement_period - 1)
    )
    return observed_start == expected_start


def forecast_spacing_summary(
    retained_forecasts: list[WindForecastRecord],
) -> tuple[list[int], int]:
    """Distinct startTime gaps inside each vintage, and how many vintages are uneven."""
    starts_by_publish_time: dict[str, list[datetime]] = defaultdict(list)
    for record in retained_forecasts:
        starts_by_publish_time[record.publish_time_utc].append(
            parse_utc_timestamp(record.start_time_utc, "startTime")
        )
    observed_spacings_minutes: set[int] = set()
    vintages_with_uneven_spacing = 0
    for start_times in starts_by_publish_time.values():
        ordered_starts = sorted(set(start_times))
        if len(ordered_starts) < 2:
            continue
        gaps_minutes = [
            int((current_start - previous_start).total_seconds() // 60)
            for previous_start, current_start in zip(ordered_starts, ordered_starts[1:], strict=False)
        ]
        observed_spacings_minutes.update(gaps_minutes)
        if len(set(gaps_minutes)) > 1:
            vintages_with_uneven_spacing += 1
    return sorted(observed_spacings_minutes), vintages_with_uneven_spacing


def count_generation_problems(generation_values: list[int | None]) -> tuple[int, int]:
    missing_values = sum(value is None for value in generation_values)
    negative_values = sum(value is not None and value < 0 for value in generation_values)
    return missing_values, negative_values
