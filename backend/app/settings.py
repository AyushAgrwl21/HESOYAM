"""Environment configuration for the pilot API."""

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("wind_procurement.settings")


class Settings(BaseSettings):
    """Runtime settings loaded from the process environment and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    elexon_base_url: str = "https://data.elexon.co.uk/bmrs/api/v1"
    study_start: date = date(2026, 1, 1)
    study_end: date = date(2026, 1, 31)
    fuel_type: Literal["WIND"] = "WIND"
    decision_timezone: str = "Europe/London"
    decision_cutoff_local: str = "09:00"
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173"
    )
    log_level: str = "INFO"
    cache_path: str = "data/wind_procurement.sqlite"
    http_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    http_read_timeout_seconds: float = Field(default=120.0, gt=0)
    http_max_attempts: int = Field(default=3, ge=1, le=8)
    http_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    forecast_publish_lookback_days: int = Field(default=3, ge=0, le=14)
    forecast_publish_lookahead_days: int = Field(default=3, ge=0, le=14)

    @field_validator("elexon_base_url")
    @classmethod
    def elexon_base_url_must_be_an_absolute_http_url(cls, candidate_url: str) -> str:
        parsed_url = urlsplit(candidate_url.strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError(
                "ELEXON_BASE_URL must be an absolute http or https URL, "
                "for example https://data.elexon.co.uk/bmrs/api/v1. "
                f"Received {candidate_url!r}."
            )
        if parsed_url.username or parsed_url.password:
            raise ValueError(
                "ELEXON_BASE_URL must not include a username or password. "
                "Do not embed credentials in source or in this URL."
            )
        return candidate_url.strip().rstrip("/")

    @field_validator("fuel_type", mode="before")
    @classmethod
    def fuel_type_must_be_wind(cls, candidate_fuel_type: object) -> str:
        if not isinstance(candidate_fuel_type, str):
            raise ValueError(
                "FUEL_TYPE must be the string WIND. "
                f"Received {candidate_fuel_type!r}."
            )
        normalized_fuel_type = candidate_fuel_type.strip().upper()
        if normalized_fuel_type != "WIND":
            raise ValueError(
                "FUEL_TYPE must be WIND. This pilot does not load other fuels. "
                f"Received {candidate_fuel_type!r}."
            )
        return normalized_fuel_type

    @field_validator("decision_timezone")
    @classmethod
    def decision_timezone_must_exist(cls, candidate_timezone_name: str) -> str:
        timezone_name = candidate_timezone_name.strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError(
                "DECISION_TIMEZONE must be an IANA timezone such as Europe/London. "
                f"Received {candidate_timezone_name!r}. "
                "If that name is valid, this Python environment is missing the tzdata package."
            ) from error
        return timezone_name

    @field_validator("decision_cutoff_local")
    @classmethod
    def decision_cutoff_must_be_hour_and_minute(cls, candidate_cutoff: str) -> str:
        try:
            parsed_cutoff = datetime.strptime(candidate_cutoff.strip(), "%H:%M")
        except ValueError as error:
            raise ValueError(
                "DECISION_CUTOFF_LOCAL must be a 24-hour time in HH:MM form, "
                f"for example 09:00. Received {candidate_cutoff!r}."
            ) from error
        return parsed_cutoff.strftime("%H:%M")

    @field_validator("cors_allowed_origins")
    @classmethod
    def cors_origins_must_be_explicit(cls, raw_allowed_origins: str) -> str:
        allowed_origins = [
            origin.strip()
            for origin in raw_allowed_origins.split(",")
            if origin.strip()
        ]
        if any(origin == "*" for origin in allowed_origins):
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must list explicit origins. "
                "A wildcard origin is not accepted."
            )
        for origin in allowed_origins:
            parsed_origin = urlsplit(origin)
            origin_has_path = parsed_origin.path not in {"", "/"}
            if (
                parsed_origin.scheme not in {"http", "https"}
                or not parsed_origin.hostname
                or origin_has_path
                or parsed_origin.query
                or parsed_origin.fragment
            ):
                raise ValueError(
                    "Each CORS origin must look like http://localhost:5173. "
                    f"Received {origin!r}."
                )
        return ",".join(allowed_origins)

    @field_validator("log_level")
    @classmethod
    def log_level_must_be_known(cls, candidate_log_level: str) -> str:
        normalized_log_level = candidate_log_level.strip().upper()
        known_level_names = logging.getLevelNamesMapping()
        if normalized_log_level not in known_level_names:
            raise ValueError(
                "LOG_LEVEL must be a Python logging level such as INFO or DEBUG. "
                f"Received {candidate_log_level!r}."
            )
        return normalized_log_level

    @field_validator("cache_path")
    @classmethod
    def cache_path_must_name_a_file(cls, candidate_path: str) -> str:
        stripped_path = candidate_path.strip()
        if not stripped_path or stripped_path.endswith(("/", "\\")):
            raise ValueError(
                "CACHE_PATH must be a SQLite file path, for example data/wind_procurement.sqlite."
            )
        return stripped_path

    @model_validator(mode="after")
    def study_window_must_run_forward(self) -> "Settings":
        if self.study_start > self.study_end:
            raise ValueError(
                "STUDY_START must be on or before STUDY_END. "
                f"Received {self.study_start.isoformat()} through {self.study_end.isoformat()}."
            )
        return self

    @property
    def allowed_cors_origins(self) -> list[str]:
        if not self.cors_allowed_origins:
            return []
        return self.cors_allowed_origins.split(",")

    @property
    def resolved_cache_path(self) -> Path:
        """Resolve a relative cache path from the backend directory, not the process cwd."""
        configured_path = Path(self.cache_path)
        if configured_path.is_absolute():
            return configured_path
        backend_root = Path(__file__).resolve().parents[1]
        return backend_root / configured_path


def load_settings() -> Settings:
    """Load settings, logging a direct reason when the environment is invalid."""
    try:
        return Settings()
    except ValidationError as error:
        logger.error(
            "The API configuration is invalid, so the process will not start: %s",
            error,
        )
        raise
