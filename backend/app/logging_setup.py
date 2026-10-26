"""Process logging for the API."""

import logging

from app.settings import Settings


def configure_logging(settings: Settings) -> None:
    """Send application logs to stderr in a single readable line format."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
