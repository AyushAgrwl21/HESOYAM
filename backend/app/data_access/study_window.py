"""Study-window bounds used to retain January target periods."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def forecast_publish_bounds(
    study_start: date,
    study_end: date,
    lookback_days: int,
    lookahead_days: int,
) -> tuple[datetime, datetime]:
    """Publish window wide enough to include vintages that target the study dates.

    WINDFOR cannot be filtered by target startTime. The client requests this
    publish window, then keeps rows whose startTime falls inside the study.
    """
    publish_from = datetime.combine(
        study_start - timedelta(days=lookback_days),
        time.min,
        tzinfo=timezone.utc,
    )
    publish_to = datetime.combine(
        study_end + timedelta(days=lookahead_days),
        time.min,
        tzinfo=timezone.utc,
    )
    return publish_from, publish_to


def study_target_bounds(
    study_start: date,
    study_end: date,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    """Inclusive local start and exclusive local end of the study, in UTC."""
    study_zone = ZoneInfo(timezone_name)
    window_start = datetime.combine(study_start, time.min, tzinfo=study_zone).astimezone(timezone.utc)
    window_end_exclusive = datetime.combine(
        study_end + timedelta(days=1),
        time.min,
        tzinfo=study_zone,
    ).astimezone(timezone.utc)
    return window_start, window_end_exclusive


def expected_half_hour_starts(
    study_start: date,
    study_end: date,
    timezone_name: str,
) -> list[datetime]:
    """Elapsed half-hours from each local midnight until the next local midnight.

    The walk is in UTC. Adding a half-hour to a local datetime would keep the
    skipped civil hour on a spring-forward day and would miss the repeated hour
    on a fall-back day. A normal day has 48 starts, a short day 46, and a long
    day 50.
    """
    study_zone = ZoneInfo(timezone_name)
    expected_starts: list[datetime] = []
    settlement_date = study_start
    while settlement_date <= study_end:
        local_midnight = datetime.combine(settlement_date, time.min, tzinfo=study_zone)
        next_local_midnight = datetime.combine(
            settlement_date + timedelta(days=1),
            time.min,
            tzinfo=study_zone,
        )
        half_hour_start = local_midnight.astimezone(timezone.utc)
        window_end = next_local_midnight.astimezone(timezone.utc)
        while half_hour_start < window_end:
            expected_starts.append(half_hour_start)
            half_hour_start += timedelta(minutes=30)
        settlement_date += timedelta(days=1)
    return expected_starts


def iter_settlement_chunks(
    settlement_date_from: date,
    settlement_date_to: date,
    chunk_days: int = 7,
) -> list[tuple[date, date]]:
    """Non-overlapping settlement-date chunks used only after a full-window failure."""
    chunks: list[tuple[date, date]] = []
    chunk_start = settlement_date_from
    while chunk_start <= settlement_date_to:
        chunk_end = min(
            settlement_date_to,
            chunk_start + timedelta(days=chunk_days - 1),
        )
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


def iter_publish_chunks(
    published_from_utc: datetime,
    published_to_utc: datetime,
) -> list[tuple[datetime, datetime]]:
    """Day-sized publish windows. Neighbouring chunks meet at the boundary and are deduped."""
    chunks: list[tuple[datetime, datetime]] = []
    chunk_start = published_from_utc
    while chunk_start < published_to_utc:
        chunk_end = min(published_to_utc, chunk_start + timedelta(days=1))
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end
    return chunks
