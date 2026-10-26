"""HTTP client for Elexon stream endpoints.

Retries are bounded and apply only to timeouts, connection failures, and
transient status codes. A failed request raises. It never returns stand-in rows.
"""

import json
import logging
from collections.abc import Callable, Mapping
from time import sleep

import httpx

from app.data_access.errors import ElexonResponseError, ElexonTransportError

logger = logging.getLogger("wind_procurement.http")

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
MAXIMUM_RETRY_DELAY_SECONDS = 30.0


class RetryingHttpClient:
    """GET a stream URL and require a JSON array body."""

    def __init__(
        self,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        max_attempts: int,
        retry_backoff_seconds: float,
        sleep_before_retry: Callable[[float], None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self._sleep_before_retry = sleep_before_retry or sleep
        timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RetryingHttpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_json_array(
        self,
        request_url: str,
        query_parameters: Mapping[str, str],
    ) -> list[object]:
        """Return the JSON array from one stream query."""
        last_failure: Exception | None = None
        for attempt_number in range(1, self.max_attempts + 1):
            try:
                response = self._client.get(request_url, params=dict(query_parameters))
            except httpx.TimeoutException as error:
                last_failure = ElexonTransportError(self._timeout_message(request_url, error))
                self._pause_if_retries_remain(attempt_number, None)
                continue
            except httpx.TransportError as error:
                last_failure = ElexonTransportError(
                    f"Could not connect to {request_url}. {error}"
                )
                self._pause_if_retries_remain(attempt_number, None)
                continue

            if response.status_code in TRANSIENT_STATUS_CODES:
                last_failure = ElexonTransportError(
                    self._status_message(request_url, response)
                )
                self._pause_if_retries_remain(attempt_number, response)
                continue
            if response.status_code != 200:
                raise ElexonResponseError(self._status_message(request_url, response))
            return self._decode_json_array(request_url, response)

        assert last_failure is not None
        raise last_failure

    def _pause_if_retries_remain(
        self,
        attempt_number: int,
        response: httpx.Response | None,
    ) -> None:
        if attempt_number >= self.max_attempts:
            return
        delay_seconds = self._retry_delay_seconds(attempt_number, response)
        logger.warning(
            "Elexon request attempt %s of %s failed. Retrying in %.1f seconds.",
            attempt_number,
            self.max_attempts,
            delay_seconds,
        )
        self._sleep_before_retry(delay_seconds)

    def _retry_delay_seconds(
        self,
        attempt_number: int,
        response: httpx.Response | None,
    ) -> float:
        if response is not None:
            retry_after_header = response.headers.get("Retry-After", "").strip()
            if retry_after_header.isdigit():
                return min(float(retry_after_header), MAXIMUM_RETRY_DELAY_SECONDS)
        exponential_delay = self.retry_backoff_seconds * (2 ** (attempt_number - 1))
        return min(exponential_delay, MAXIMUM_RETRY_DELAY_SECONDS)

    def _decode_json_array(self, request_url: str, response: httpx.Response) -> list[object]:
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise ElexonResponseError(
                f"{request_url} returned HTTP 200 but the body is not valid JSON. "
                "No rows were invented from it."
            ) from error
        if not isinstance(payload, list):
            raise ElexonResponseError(
                f"{request_url} returned HTTP 200 but the body is not a JSON array. "
                "The FUELHH and WINDFOR stream endpoints do not document a pagination "
                "envelope, so the client will not unwrap another shape or request a further page."
            )
        logger.info(
            "Elexon GET %s returned %s JSON rows.",
            response.request.url,
            len(payload),
        )
        return payload

    def _status_message(self, request_url: str, response: httpx.Response) -> str:
        body_excerpt = response.text[:500].strip()
        if not body_excerpt:
            body_excerpt = "The response body was empty."
        return (
            f"Elexon returned HTTP {response.status_code} for {request_url}. "
            f"{body_excerpt}"
        )

    def _timeout_message(self, request_url: str, error: Exception) -> str:
        return (
            f"The request to {request_url} timed out before a complete response arrived. "
            f"{error}"
        )
