"""HTTP and query tests. No test in this module contacts Elexon."""

from datetime import date, datetime, timezone

import httpx
import pytest

from app.data_access.errors import ElexonResponseError, ElexonTransportError, StreamQueryError
from app.data_access.elexon_stream_reader import ElexonStreamReader
from app.data_access.retrying_http_client import RetryingHttpClient
from app.data_access.stream_queries import build_fuelhh_wind_query


def test_fuelhh_query_rejects_a_mixed_settlement_and_publish_filter() -> None:
    with pytest.raises(StreamQueryError, match="cannot be sent together"):
        build_fuelhh_wind_query(
            settlement_date_from=date(2026, 1, 1),
            settlement_date_to=date(2026, 1, 2),
            publish_time_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_reader_requests_wind_actuals_without_a_publish_filter() -> None:
    recording_fetcher = RecordingFetcher(payload=[])
    stream_reader = ElexonStreamReader(
        "https://data.elexon.co.uk/bmrs/api/v1",
        recording_fetcher,
    )

    stream_reader.read_half_hourly_wind_actuals(date(2026, 1, 1), date(2026, 1, 31))

    request_url, query_parameters = recording_fetcher.calls[0]
    assert request_url.endswith("/datasets/FUELHH/stream")
    assert query_parameters == {
        "settlementDateFrom": "2026-01-01",
        "settlementDateTo": "2026-01-31",
        "fuelType": "WIND",
    }
    assert "publishDateTimeFrom" not in query_parameters


def test_reader_requests_forecasts_by_publish_window_only() -> None:
    recording_fetcher = RecordingFetcher(payload=[])
    stream_reader = ElexonStreamReader(
        "https://data.elexon.co.uk/bmrs/api/v1",
        recording_fetcher,
    )

    stream_reader.read_wind_forecast_vintages(
        datetime(2025, 12, 29, tzinfo=timezone.utc),
        datetime(2026, 2, 3, tzinfo=timezone.utc),
    )

    request_url, query_parameters = recording_fetcher.calls[0]
    assert request_url.endswith("/datasets/WINDFOR/stream")
    assert query_parameters == {
        "publishDateTimeFrom": "2025-12-29T00:00:00Z",
        "publishDateTimeTo": "2026-02-03T00:00:00Z",
    }


def test_transient_status_is_retried_and_then_returns_the_array() -> None:
    attempted_calls = {"count": 0}

    def handle_request(request: httpx.Request) -> httpx.Response:
        del request
        attempted_calls["count"] += 1
        if attempted_calls["count"] == 1:
            return httpx.Response(503, json={"message": "temporary"})
        return httpx.Response(200, json=[{"dataset": "WINDFOR"}])

    client = RetryingHttpClient(
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_attempts=2,
        retry_backoff_seconds=0,
        sleep_before_retry=lambda delay_seconds: None,
        transport=httpx.MockTransport(handle_request),
    )

    payload = client.fetch_json_array("https://example.test/datasets/WINDFOR/stream", {})

    assert payload == [{"dataset": "WINDFOR"}]
    assert attempted_calls["count"] == 2


def test_http_400_is_not_retried_and_returns_no_rows() -> None:
    attempted_calls = {"count": 0}

    def handle_request(request: httpx.Request) -> httpx.Response:
        del request
        attempted_calls["count"] += 1
        return httpx.Response(
            400,
            json={"errors": {"message": "The Settlement Date fields cannot be set when a Publish Date field is set."}},
        )

    client = RetryingHttpClient(
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_attempts=3,
        retry_backoff_seconds=5,
        sleep_before_retry=lambda delay_seconds: (_ for _ in ()).throw(
            AssertionError("A 400 response must not be retried.")
        ),
        transport=httpx.MockTransport(handle_request),
    )

    with pytest.raises(ElexonResponseError, match="HTTP 400"):
        client.fetch_json_array("https://example.test/datasets/FUELHH/stream", {})
    assert attempted_calls["count"] == 1


def test_non_array_success_body_is_rejected_without_unwrapping() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"data": [{"generation": 1}]})

    client = RetryingHttpClient(
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_attempts=1,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handle_request),
    )

    with pytest.raises(ElexonResponseError, match="not a JSON array"):
        client.fetch_json_array("https://example.test/datasets/WINDFOR/stream", {})


def test_timeouts_stop_after_the_bounded_attempts() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = RetryingHttpClient(
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_attempts=2,
        retry_backoff_seconds=0,
        sleep_before_retry=lambda delay_seconds: None,
        transport=httpx.MockTransport(handle_request),
    )

    with pytest.raises(ElexonTransportError, match="timed out"):
        client.fetch_json_array("https://example.test/datasets/FUELHH/stream", {})


class RecordingFetcher:
    """Test double. It records calls and returns the supplied payload."""

    def __init__(self, payload: list[object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str]]] = []

    def fetch_json_array(
        self,
        request_url: str,
        query_parameters: dict[str, str],
    ) -> list[object]:
        self.calls.append((request_url, dict(query_parameters)))
        return self.payload
