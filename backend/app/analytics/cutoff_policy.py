"""Purchasing-cutoff policy.

The default local time is a pilot assumption. It is not an EPEX auction gate,
BSC Gate Closure, or the BSC Submission Deadline. Changing the clock time does
not change that basis: this pilot has no official deadline to apply.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PILOT_CUTOFF_BASIS = "pilot_assumption"

CUTOFF_CONVENTION = (
    "The delivery date is the calendar date of the interval start in the decision "
    "timezone. FUELHH settlementDate is that date. WINDFOR has no settlement date, "
    "so its delivery date is the local date of startTime. The cutoff is the configured "
    "clock time on the previous calendar day in that timezone, converted to UTC. "
    "January 2026 in Europe/London is GMT, so the default 09:00 is 09:00Z; the "
    "conversion still runs. A forecast stays on its own startTime."
)

GENERATION_UNIT = "MW"
ERROR_UNIT = "MW"

REQUESTED_WINDOW_DENOMINATOR = (
    "The denominator is the local half-hour starts inside the requested delivery "
    "dates. When a settlement period is requested, only that period is included. "
    "Coverage percent is 100 times the matched intervals divided by this count. "
    "JSON null is a missing measurement. A stored zero is measured zero MW."
)

MAX_REQUESTED_DAYS = 62

REFRESH_STRATEGY = (
    "Dashboard reads use the SQLite cache written by a successful "
    "python -m app.ingest. They do not call Elexon. A failed ingest does not "
    "replace the previous cache and is not stored as an empty success. Run ingest "
    "again to refresh the rows, then repeat the read."
)

NULL_GENERATION_MEANING = (
    "JSON null is a missing measurement. Zero is a measured generation of 0 MW."
)

METRIC_DEFINITIONS = {
    "signed_error": "On a matched interval, signed error MW = forecast MW − actual MW.",
    "mean_error": "Mean of the signed errors over matched intervals only, in MW.",
    "mean_absolute_error": "Mean of the absolute signed errors over matched intervals only, in MW.",
    "root_mean_squared_error": (
        "Square root of the mean squared signed error over matched intervals, in MW. "
        "The divisor is the matched count."
    ),
    "weighted_absolute_percentage_error": (
        "100 × sum(absolute error) / sum(actual MW) over matched intervals, "
        "only when the actual sum is positive. Otherwise it is withheld."
    ),
    "coverage_percent": "100 × matched intervals / the requested-window denominator.",
    "mape": "not_calculated",
    "reference": "docs/ANALYTICS.md",
}


def parse_cutoff_local(cutoff_local: str) -> str:
    """Return HH:MM or raise ValueError when the clock time is not usable."""
    try:
        parsed_cutoff = datetime.strptime(cutoff_local.strip(), "%H:%M")
    except ValueError as error:
        raise ValueError(
            "decision_cutoff_local must be a 24-hour time in HH:MM form, "
            f"for example 09:00. Received {cutoff_local!r}."
        ) from error
    return parsed_cutoff.strftime("%H:%M")


COVERAGE_DENOMINATOR_DEFINITION = (
    "The denominator is every local half-hour settlement start from the first "
    "delivery date through the last, inclusive. January 2026 has 48 starts on "
    "each of 31 days because Europe/London does not change clocks. A clock-change "
    "day has 46 or 50 starts, and the count comes from that timezone rather than "
    "from a fixed 48. Coverage percent is 100 times the matched-interval count "
    "divided by this denominator. Matched intervals are the only intervals in the "
    "error averages. An interval without a usable forecast and an interval without "
    "a usable actual are both counted; an empty interval is in both counts."
)


def decision_cutoff_utc(
    delivery_date: date,
    cutoff_local: str,
    timezone_name: str,
) -> datetime:
    """Return the UTC instant of the cutoff on the day before delivery_date.

    cutoff_local is HH:MM in timezone_name. The bound is inclusive: a forecast
    published at this instant is eligible, and one published a second later is not.
    """
    hour_text, minute_text = cutoff_local.split(":", maxsplit=1)
    decision_day = delivery_date - timedelta(days=1)
    local_cutoff = datetime(
        decision_day.year,
        decision_day.month,
        decision_day.day,
        int(hour_text),
        int(minute_text),
        tzinfo=ZoneInfo(timezone_name),
    )
    return local_cutoff.astimezone(timezone.utc)
