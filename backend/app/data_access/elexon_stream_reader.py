"""Reader for the FUELHH and WINDFOR stream endpoints."""

from datetime import date, datetime
from typing import Protocol

from app.data_access.stream_queries import (
    FUELHH_STREAM_PATH,
    WINDFOR_STREAM_PATH,
    build_fuelhh_wind_query,
    build_windfor_query,
)


class JsonArrayFetcher(Protocol):
    """Fetches one stream response. Implementations must not invent rows."""

    def fetch_json_array(
        self,
        request_url: str,
        query_parameters: dict[str, str],
    ) -> list[object]:
        """Return the JSON array for this URL and query."""


class ElexonStreamReader:
    """Calls only the documented FUELHH and WINDFOR stream paths."""

    def __init__(self, elexon_base_url: str, json_array_fetcher: JsonArrayFetcher) -> None:
        self.elexon_base_url = elexon_base_url.rstrip("/")
        self._json_array_fetcher = json_array_fetcher

    def read_half_hourly_wind_actuals(
        self,
        settlement_date_from: date,
        settlement_date_to: date,
    ) -> list[object]:
        """Load FUELHH rows with fuelType WIND for a settlement-date window."""
        query_parameters = build_fuelhh_wind_query(
            settlement_date_from=settlement_date_from,
            settlement_date_to=settlement_date_to,
        )
        request_url = f"{self.elexon_base_url}{FUELHH_STREAM_PATH}"
        return self._json_array_fetcher.fetch_json_array(request_url, query_parameters)

    def read_wind_forecast_vintages(
        self,
        published_from_utc: datetime,
        published_to_utc: datetime,
    ) -> list[object]:
        """Load WINDFOR rows published inside the given window, including every vintage."""
        query_parameters = build_windfor_query(
            published_from_utc=published_from_utc,
            published_to_utc=published_to_utc,
        )
        request_url = f"{self.elexon_base_url}{WINDFOR_STREAM_PATH}"
        return self._json_array_fetcher.fetch_json_array(request_url, query_parameters)
