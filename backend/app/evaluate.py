"""Score the cached study window from the command line.

Usage from the backend directory:

    python -m app.evaluate

This reads the SQLite cache. It does not call Elexon and it does not create
rows when the cache is missing.
"""

import json
import sys

from pydantic import ValidationError

from app.analytics.forecast_evaluation import evaluate_decision_time_forecast
from app.data_access.sqlite_cache import load_cached_extract
from app.data_access.study_window import expected_half_hour_starts
from app.settings import load_settings


def main() -> int:
    """Print decision-time and latest-available summaries for the cached extract."""
    try:
        settings = load_settings()
    except ValidationError as error:
        print(f"Evaluation did not start because the configuration is invalid. {error}", file=sys.stderr)
        return 1
    cache_path = settings.resolved_cache_path
    try:
        cached_extract = load_cached_extract(cache_path)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1

    first_day_starts = expected_half_hour_starts(
        settings.study_start,
        settings.study_start,
        settings.decision_timezone,
    )
    vintage_target = first_day_starts[0].strftime("%Y-%m-%dT%H:%M:%SZ")
    evaluation = evaluate_decision_time_forecast(
        cached_extract.actuals,
        cached_extract.forecasts,
        study_start=settings.study_start,
        study_end=settings.study_end,
        decision_timezone=settings.decision_timezone,
        decision_cutoff_local=settings.decision_cutoff_local,
        vintage_target_start_time_utc=vintage_target,
    )
    summary = evaluation.model_dump(
        mode="json",
        exclude={"primary": {"series"}, "latest_available": {"series"}},
    )
    print(
        json.dumps(
            {
                "source": "local sqlite cache of an earlier Elexon extract",
                "live_elexon_request": False,
                "cache_path": str(cache_path),
                "fetched_at_utc": cached_extract.fetched_at_utc,
                "vintage_evolution_target_start_time_utc": vintage_target,
                "primary_series_rows_omitted_from_this_printout": len(evaluation.primary.series),
                "latest_available_series_rows_omitted_from_this_printout": len(
                    evaluation.latest_available.series
                ),
                "note": (
                    "Primary metrics use the latest publishTime at or before each "
                    "delivery date's cutoff. Latest-available metrics include later "
                    "publications and were not available to the original purchaser."
                ),
                "evaluation": summary,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
