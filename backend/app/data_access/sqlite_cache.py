"""SQLite cache of the latest successful study extract.

The file is replaced as a whole on each successful rerun. A failed fetch does
not delete the previous successful extract.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.data_access.record_parsing import WindActualRecord, WindForecastRecord
from app.schemas.ingestion import IngestionReport

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS ingestion_runs (
        ingestion_run_id INTEGER PRIMARY KEY,
        fetched_at_utc TEXT NOT NULL,
        report_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wind_actuals (
        settlement_date TEXT NOT NULL,
        settlement_period INTEGER NOT NULL,
        fuel_type TEXT NOT NULL,
        dataset TEXT NOT NULL,
        publish_time_utc TEXT NOT NULL,
        start_time_utc TEXT NOT NULL,
        generation_mw INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wind_forecasts (
        publish_time_utc TEXT NOT NULL,
        start_time_utc TEXT NOT NULL,
        dataset TEXT NOT NULL,
        generation_mw INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rejected_stream_rows (
        stream_name TEXT NOT NULL,
        reason TEXT NOT NULL
    )
    """,
)


def replace_study_cache(
    cache_path: Path,
    report: IngestionReport,
    retained_actuals: list[WindActualRecord],
    retained_forecasts: list[WindForecastRecord],
    rejected_reasons: list[tuple[str, str]],
) -> None:
    """Write one complete extract. The previous extract remains if this raises."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(cache_path)
    try:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        with connection:
            connection.execute("DELETE FROM wind_actuals")
            connection.execute("DELETE FROM wind_forecasts")
            connection.execute("DELETE FROM rejected_stream_rows")
            connection.execute("DELETE FROM ingestion_runs")
            connection.execute(
                "INSERT INTO ingestion_runs (fetched_at_utc, report_json) VALUES (?, ?)",
                (report.fetched_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), report.model_dump_json()),
            )
            connection.executemany(
                """
                INSERT INTO wind_actuals (
                    settlement_date, settlement_period, fuel_type, dataset,
                    publish_time_utc, start_time_utc, generation_mw
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.settlement_date.isoformat(),
                        record.settlement_period,
                        record.fuel_type,
                        record.dataset,
                        record.publish_time_utc,
                        record.start_time_utc,
                        record.generation_mw,
                    )
                    for record in retained_actuals
                ],
            )
            connection.executemany(
                """
                INSERT INTO wind_forecasts (
                    publish_time_utc, start_time_utc, dataset, generation_mw
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        record.publish_time_utc,
                        record.start_time_utc,
                        record.dataset,
                        record.generation_mw,
                    )
                    for record in retained_forecasts
                ],
            )
            connection.executemany(
                "INSERT INTO rejected_stream_rows (stream_name, reason) VALUES (?, ?)",
                rejected_reasons,
            )
    finally:
        connection.close()


@dataclass(frozen=True)
class CachedStudyExtract:
    """Rows from the latest successful ingestion, with the fetch time kept."""

    fetched_at_utc: str
    actuals: list[WindActualRecord]
    forecasts: list[WindForecastRecord]


def load_cached_extract(cache_path: Path) -> CachedStudyExtract:
    """Read the cached extract. A missing file is not replaced with invented rows."""
    if not cache_path.is_file():
        raise FileNotFoundError(
            f"No study cache at {cache_path}. Run python -m app.ingest before scoring. "
            "Evaluation does not invent rows when the cache is missing."
        )
    connection = sqlite3.connect(f"{cache_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        fetched_row = connection.execute(
            "SELECT fetched_at_utc FROM ingestion_runs ORDER BY ingestion_run_id DESC LIMIT 1"
        ).fetchone()
        if fetched_row is None:
            raise FileNotFoundError(
                f"The cache at {cache_path} has no ingestion run. "
                "Evaluation does not invent rows."
            )
        actuals = [
            WindActualRecord(
                dataset=dataset,
                publish_time_utc=publish_time_utc,
                start_time_utc=start_time_utc,
                settlement_date=settlement_date,
                settlement_period=settlement_period,
                fuel_type=fuel_type,
                generation_mw=generation_mw,
            )
            for (
                dataset,
                publish_time_utc,
                start_time_utc,
                settlement_date,
                settlement_period,
                fuel_type,
                generation_mw,
            ) in connection.execute(
                """
                SELECT dataset, publish_time_utc, start_time_utc, settlement_date,
                       settlement_period, fuel_type, generation_mw
                FROM wind_actuals
                """
            )
        ]
        forecasts = [
            WindForecastRecord(
                dataset=dataset,
                publish_time_utc=publish_time_utc,
                start_time_utc=start_time_utc,
                generation_mw=generation_mw,
            )
            for dataset, publish_time_utc, start_time_utc, generation_mw in connection.execute(
                """
                SELECT dataset, publish_time_utc, start_time_utc, generation_mw
                FROM wind_forecasts
                """
            )
        ]
    finally:
        connection.close()
    return CachedStudyExtract(
        fetched_at_utc=str(fetched_row[0]),
        actuals=actuals,
        forecasts=forecasts,
    )


@dataclass(frozen=True)
class CacheInspection:
    """A cheap cache check. It does not load generation rows."""

    status: Literal["present", "missing", "unreadable"]
    fetched_at_utc: str | None
    actual_rows: int | None
    forecast_rows: int | None
    ingestion_coverage_status: Literal["complete", "incomplete"] | None
    detail: str | None


def inspect_cache(cache_path: Path) -> CacheInspection:
    """Report whether a successful extract is present without scoring it."""
    if not cache_path.is_file():
        return CacheInspection(
            status="missing",
            fetched_at_utc=None,
            actual_rows=None,
            forecast_rows=None,
            ingestion_coverage_status=None,
            detail=(
                f"No study cache at {cache_path}. Run python -m app.ingest. "
                "A missing cache is not an empty generation series."
            ),
        )
    try:
        connection = sqlite3.connect(f"{cache_path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as error:
        return _unreadable_cache(str(error))
    try:
        fetched_row = connection.execute(
            "SELECT fetched_at_utc, report_json FROM ingestion_runs ORDER BY ingestion_run_id DESC LIMIT 1"
        ).fetchone()
        if fetched_row is None:
            return _unreadable_cache("The study cache has no ingestion run.")
        actual_rows = connection.execute("SELECT COUNT(*) FROM wind_actuals").fetchone()
        forecast_rows = connection.execute("SELECT COUNT(*) FROM wind_forecasts").fetchone()
        coverage_status = IngestionReport.model_validate_json(fetched_row[1]).coverage_status
    except (sqlite3.Error, ValidationError, TypeError, KeyError) as error:
        return _unreadable_cache(str(error))
    finally:
        connection.close()
    return CacheInspection(
        status="present",
        fetched_at_utc=str(fetched_row[0]),
        actual_rows=int(actual_rows[0]) if actual_rows is not None else 0,
        forecast_rows=int(forecast_rows[0]) if forecast_rows is not None else 0,
        ingestion_coverage_status=coverage_status,
        detail=None,
    )


def load_ingestion_report(cache_path: Path) -> IngestionReport:
    """Read the provenance report stored with the latest successful extract."""
    if not cache_path.is_file():
        raise FileNotFoundError(
            f"No study cache at {cache_path}. Run python -m app.ingest before scoring. "
            "Evaluation does not invent rows when the cache is missing."
        )
    connection = sqlite3.connect(f"{cache_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        fetched_row = connection.execute(
            "SELECT report_json FROM ingestion_runs ORDER BY ingestion_run_id DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if fetched_row is None:
        raise FileNotFoundError(
            f"The cache at {cache_path} has no ingestion run. Evaluation does not invent rows."
        )
    return IngestionReport.model_validate_json(fetched_row[0])


def _unreadable_cache(detail: str) -> CacheInspection:
    return CacheInspection(
        status="unreadable",
        fetched_at_utc=None,
        actual_rows=None,
        forecast_rows=None,
        ingestion_coverage_status=None,
        detail=f"The study cache could not be read. {detail}",
    )
