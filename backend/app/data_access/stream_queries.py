"""Query parameters for the two in-scope stream endpoints.

The FUELHH documentation says settlement-date filters and publish-date filters
cannot be combined. WINDFOR stream accepts only a publish-time window.
Neither stream documents a page, offset, or cursor parameter.
"""

from datetime import date, datetime

from app.data_access.timestamps import format_utc_timestamp
from app.data_access.errors import StreamQueryError

FUELHH_STREAM_PATH = "/datasets/FUELHH/stream"
WINDFOR_STREAM_PATH = "/datasets/WINDFOR/stream"


def build_fuelhh_wind_query(
    settlement_date_from: date,
    settlement_date_to: date,
    fuel_type: str = "WIND",
    publish_time_from: datetime | None = None,
    publish_time_to: datetime | None = None,
) -> dict[str, str]:
    """Build the FUELHH wind query, or reject a mixed settlement/publish filter."""
    if publish_time_from is not None or publish_time_to is not None:
        raise StreamQueryError(
            "FUELHH was not requested. Settlement-date filters and publish-date "
            "filters cannot be sent together; the Insights API returns HTTP 400 "
            "for that combination. Actuals use settlementDateFrom and settlementDateTo only."
        )
    if fuel_type != "WIND":
        raise StreamQueryError(
            f"FUELHH fuelType must be WIND for this pilot. Received {fuel_type!r}."
        )
    if settlement_date_from > settlement_date_to:
        raise StreamQueryError(
            "settlementDateFrom must be on or before settlementDateTo. "
            f"Received {settlement_date_from.isoformat()} through {settlement_date_to.isoformat()}."
        )
    return {
        "settlementDateFrom": settlement_date_from.isoformat(),
        "settlementDateTo": settlement_date_to.isoformat(),
        "fuelType": fuel_type,
    }


def build_windfor_query(
    published_from_utc: datetime,
    published_to_utc: datetime,
) -> dict[str, str]:
    """Build the WINDFOR publish-time query. The upper bound is sent to the API."""
    if published_from_utc > published_to_utc:
        raise StreamQueryError(
            "WINDFOR publishDateTimeFrom must be at or before publishDateTimeTo."
        )
    return {
        "publishDateTimeFrom": format_utc_timestamp(published_from_utc),
        "publishDateTimeTo": format_utc_timestamp(published_to_utc),
    }
