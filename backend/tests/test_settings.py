import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_default_settings_describe_the_january_pilot() -> None:
    settings = Settings()

    assert settings.study_start.isoformat() == "2026-01-01"
    assert settings.study_end.isoformat() == "2026-01-31"
    assert settings.fuel_type == "WIND"
    assert settings.decision_cutoff_local == "09:00"
    assert settings.decision_timezone == "Europe/London"
    assert settings.allowed_cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_reversed_study_window_names_the_two_dates() -> None:
    with pytest.raises(ValidationError, match="STUDY_START must be on or before STUDY_END"):
        Settings(study_start="2026-01-31", study_end="2026-01-01")


def test_non_wind_fuel_is_rejected() -> None:
    with pytest.raises(ValidationError, match="FUEL_TYPE must be WIND"):
        Settings(fuel_type="CCGT")


def test_cutoff_must_be_an_hour_and_minute() -> None:
    with pytest.raises(ValidationError, match="DECISION_CUTOFF_LOCAL"):
        Settings(decision_cutoff_local="9am")


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="DECISION_TIMEZONE"):
        Settings(decision_timezone="London")


def test_credential_in_the_elexon_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not include a username or password"):
        Settings(elexon_base_url="https://user:secret@data.elexon.co.uk/bmrs/api/v1")


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        Settings(cors_allowed_origins="*")
