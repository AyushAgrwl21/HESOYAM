"""Run a repeatable FUELHH and WINDFOR ingestion from the command line.

Usage from the backend directory:

    python -m app.ingest
"""

import logging
import sys

from pydantic import ValidationError

from app.data_access.errors import ElexonClientError
from app.data_access.ingestion import ingest_study_window
from app.logging_setup import configure_logging
from app.settings import load_settings

logger = logging.getLogger("wind_procurement.ingest")


def main() -> int:
    """Fetch the configured study window and print the validation report."""
    try:
        settings = load_settings()
    except ValidationError as error:
        print(f"Ingestion did not start because the configuration is invalid. {error}", file=sys.stderr)
        return 1
    configure_logging(settings)
    try:
        report = ingest_study_window(settings)
    except ElexonClientError as error:
        logger.error("Ingestion failed: %s", error)
        print(
            "Ingestion failed and the previous cache was not replaced. "
            f"{error}",
            file=sys.stderr,
        )
        return 1
    print(report.model_dump_json(indent=2))
    if report.coverage_status != "complete":
        print(
            "Retrieval coverage is incomplete. Forecast error was not calculated.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
