"""Error summaries for pairs that already share one UTC startTime.

MAPE is intentionally absent. It divides by each actual, so a zero or a very
small actual dominates or breaks the result. WAPE divides by the sum of actuals
once, and it is withheld when that sum is not positive.
"""

from decimal import Decimal

from app.analytics.cutoff_policy import ERROR_UNIT, GENERATION_UNIT
from app.schemas.evaluation import ErrorMetrics

WAPE_CALCULATED = "calculated"
WAPE_NON_POSITIVE_ACTUAL_SUM = "undefined_non_positive_actual_sum"
WAPE_NO_MATCHES = "not_applicable_no_matches"


def calculate_error_metrics(paired_generation_mw: list[tuple[int, int]]) -> ErrorMetrics:
    """Summarise (forecast MW, actual MW) pairs.

    Mean error is mean(forecast - actual). RMSE divides the squared errors by
    the matched count, not by count minus one. An empty pair list does not
    become a zero error.
    """
    matched_interval_count = len(paired_generation_mw)
    if matched_interval_count == 0:
        return _empty_metrics()

    signed_errors = [
        Decimal(forecast_mw) - Decimal(actual_mw)
        for forecast_mw, actual_mw in paired_generation_mw
    ]
    absolute_errors = [abs(signed_error) for signed_error in signed_errors]
    matched_count = Decimal(matched_interval_count)
    mean_error = sum(signed_errors, Decimal(0)) / matched_count
    mean_absolute_error = sum(absolute_errors, Decimal(0)) / matched_count
    mean_squared_error = sum(
        (signed_error * signed_error for signed_error in signed_errors),
        Decimal(0),
    ) / matched_count
    actual_sum = sum(
        (Decimal(actual_mw) for _, actual_mw in paired_generation_mw),
        Decimal(0),
    )
    if actual_sum > 0:
        wape = sum(absolute_errors, Decimal(0)) / actual_sum * Decimal(100)
        wape_status = WAPE_CALCULATED
        wape_value: float | None = float(wape)
    else:
        wape_status = WAPE_NON_POSITIVE_ACTUAL_SUM
        wape_value = None
    return ErrorMetrics(
        matched_interval_count=matched_interval_count,
        mean_error_mw=float(mean_error),
        mean_absolute_error_mw=float(mean_absolute_error),
        root_mean_squared_error_mw=float(mean_squared_error.sqrt()),
        weighted_absolute_percentage_error_percent=wape_value,
        wape_status=wape_status,
        generation_unit=GENERATION_UNIT,
        error_unit=ERROR_UNIT,
    )


def _empty_metrics() -> ErrorMetrics:
    return ErrorMetrics(
        matched_interval_count=0,
        mean_error_mw=None,
        mean_absolute_error_mw=None,
        root_mean_squared_error_mw=None,
        weighted_absolute_percentage_error_percent=None,
        wape_status=WAPE_NO_MATCHES,
        generation_unit=GENERATION_UNIT,
        error_unit=ERROR_UNIT,
    )
