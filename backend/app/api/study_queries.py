"""Validate the delivery window, cutoff, and vintage target for one read."""

from datetime import date

from pydantic import BaseModel, Field

from app.analytics.cutoff_policy import MAX_REQUESTED_DAYS, parse_cutoff_local
from app.data_access.timestamps import RecordParseError, parse_utc_timestamp
from app.settings import Settings


class InvalidStudyQuery(ValueError):
    """The caller asked for a window this API will not score."""


class StudyWindowQuery(BaseModel):
    """Optional filters. Omitted dates mean the configured study window."""

    delivery_date: date | None = None
    date_from: date | None = None
    date_to: date | None = None
    decision_cutoff_local: str | None = None
    settlement_period: int | None = Field(default=None, ge=1, le=50)


class VintageQuery(StudyWindowQuery):
    """One target interval, either as a timestamp or as a settlement period."""

    start_time: str | None = None


class ResolvedWindow(BaseModel):
    delivery_start: date
    delivery_end: date
    decision_cutoff_local: str
    settlement_period: int | None


def resolve_window(settings: Settings, query: StudyWindowQuery) -> ResolvedWindow:
    """Apply defaults and reject ranges outside the configured study."""
    if query.delivery_date is not None and (query.date_from is not None or query.date_to is not None):
        raise InvalidStudyQuery(
            "Pass delivery_date or date_from and date_to, not both. "
            f"Received delivery_date {query.delivery_date.isoformat()}."
        )
    if query.delivery_date is not None:
        delivery_start = query.delivery_date
        delivery_end = query.delivery_date
    else:
        delivery_start = query.date_from or settings.study_start
        delivery_end = query.date_to or settings.study_end
    if delivery_start > delivery_end:
        raise InvalidStudyQuery(
            "date_from must be on or before date_to. "
            f"Received {delivery_start.isoformat()} through {delivery_end.isoformat()}."
        )
    if delivery_start < settings.study_start or delivery_end > settings.study_end:
        raise InvalidStudyQuery(
            "The requested dates must stay inside the configured study window "
            f"{settings.study_start.isoformat()} through {settings.study_end.isoformat()}. "
            f"Received {delivery_start.isoformat()} through {delivery_end.isoformat()}."
        )
    requested_days = (delivery_end - delivery_start).days + 1
    if requested_days > MAX_REQUESTED_DAYS:
        raise InvalidStudyQuery(
            f"A read can cover at most {MAX_REQUESTED_DAYS} delivery dates. "
            f"Received {requested_days}. Narrow date_from and date_to."
        )
    try:
        cutoff_local = parse_cutoff_local(
            query.decision_cutoff_local or settings.decision_cutoff_local
        )
    except ValueError as error:
        raise InvalidStudyQuery(str(error)) from error
    return ResolvedWindow(
        delivery_start=delivery_start,
        delivery_end=delivery_end,
        decision_cutoff_local=cutoff_local,
        settlement_period=query.settlement_period,
    )


def resolve_vintage_target(
    settings: Settings,
    query: VintageQuery,
    known_starts: dict[tuple[date, int], str],
) -> str:
    """Choose one startTime. A missing target is a 422, not an empty series."""
    window = resolve_window(settings, query)
    has_period = query.delivery_date is not None or query.settlement_period is not None
    if query.start_time and has_period:
        raise InvalidStudyQuery(
            "Pass start_time, or delivery_date together with settlement_period. Do not pass both."
        )
    if query.start_time:
        try:
            parsed_start = parse_utc_timestamp(query.start_time, "start_time")
        except RecordParseError as error:
            raise InvalidStudyQuery(str(error)) from error
        return parsed_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    if query.delivery_date is None or query.settlement_period is None:
        raise InvalidStudyQuery(
            "Choose one target interval with start_time, or with delivery_date and settlement_period."
        )
    if not (window.delivery_start <= query.delivery_date <= window.delivery_end):
        raise InvalidStudyQuery(
            "delivery_date must stay inside the configured study window "
            f"{settings.study_start.isoformat()} through {settings.study_end.isoformat()}."
        )
    start_time_utc = known_starts.get((query.delivery_date, query.settlement_period))
    if start_time_utc is None:
        raise InvalidStudyQuery(
            f"Settlement period {query.settlement_period} does not occur on "
            f"{query.delivery_date.isoformat()} in {settings.decision_timezone}."
        )
    return start_time_utc


def describe_window(
    delivery_start: date,
    delivery_end: date,
    settlement_period: int | None,
    interval_count: int,
) -> str:
    """Explain an empty or partial slice without turning a gap into zero generation."""
    if interval_count == 0:
        period_text = (
            f" Settlement period {settlement_period} does not occur in this window."
            if settlement_period is not None
            else ""
        )
        return (
            "The requested window has no settlement intervals."
            + period_text
            + " No generation value was created."
        )
    period_text = (
        f" Settlement period {settlement_period} only."
        if settlement_period is not None
        else " All settlement periods in those dates."
    )
    return (
        f"{interval_count} settlement intervals from {delivery_start.isoformat()} "
        f"through {delivery_end.isoformat()}.{period_text} "
        "JSON null is missing. Zero is measured zero MW."
    )
