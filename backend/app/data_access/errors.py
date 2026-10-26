"""Failures from the Elexon stream client.

These errors mean the requested rows were not retrieved. Callers must not
replace them with example or synthetic measurements.
"""


class ElexonClientError(Exception):
    """The stream request could not be completed."""


class StreamQueryError(ElexonClientError):
    """The query was rejected locally because the Insights API would reject it."""


class ElexonTransportError(ElexonClientError):
    """The connection failed or timed out after the bounded retry attempts."""


class ElexonResponseError(ElexonClientError):
    """Elexon returned a response the client cannot use as stream rows."""
