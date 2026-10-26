"""Timezone-aware timestamp parsing for Elexon stream fields."""

from datetime import datetime, timezone

from app.data_access.errors import StreamQueryError


class RecordParseError(ValueError):
    """One stream row cannot be stored because a required field is unusable."""


def parse_utc_timestamp(raw_timestamp: object, field_name: str) -> datetime:
    """Parse an ISO-8601 timestamp and return it in UTC.

    Naive timestamps are rejected. The client does not assume a timezone.
    """
    if not isinstance(raw_timestamp, str) or not raw_timestamp.strip():
        raise RecordParseError(
            f"{field_name} must be a timezone-aware ISO-8601 string. "
            f"Received {raw_timestamp!r}."
        )
    candidate_text = raw_timestamp.strip()
    if candidate_text.endswith(("Z", "z")):
        candidate_text = candidate_text[:-1] + "+00:00"
    try:
        parsed_timestamp = datetime.fromisoformat(candidate_text)
    except ValueError as error:
        raise RecordParseError(
            f"{field_name} is not a valid ISO-8601 timestamp. Received {raw_timestamp!r}."
        ) from error
    if parsed_timestamp.tzinfo is None:
        raise RecordParseError(
            f"{field_name} must include a timezone offset. Received {raw_timestamp!r}."
        )
    return parsed_timestamp.astimezone(timezone.utc)


def format_utc_timestamp(timestamp_value: datetime) -> str:
    """Format a timezone-aware timestamp as UTC with a Z suffix."""
    if timestamp_value.tzinfo is None:
        raise StreamQueryError(
            "Cannot format a naive timestamp for the Elexon query. "
            "Provide a timezone-aware UTC instant."
        )
    utc_timestamp = timestamp_value.astimezone(timezone.utc).replace(microsecond=0)
    return utc_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
