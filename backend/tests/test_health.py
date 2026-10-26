import socket

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_health_reports_the_pilot_configuration_and_no_generation_values(tmp_path) -> None:
    application_settings = Settings(cache_path=str(tmp_path / "missing.sqlite"))
    client = TestClient(create_app(application_settings))

    response = client.get("/health")

    assert response.status_code == 200
    health_payload = response.json()
    assert health_payload["status"] == "ok"
    assert health_payload["service_name"] == "wind-procurement-api"
    assert health_payload["study_start"] == "2026-01-01"
    assert health_payload["study_end"] == "2026-01-31"
    assert health_payload["fuel_type"] == "WIND"
    assert health_payload["decision_timezone"] == "Europe/London"
    assert health_payload["decision_cutoff_local"] == "09:00"
    assert health_payload["cutoff_basis"] == "pilot_assumption"
    assert health_payload["elexon_request_status"] == "not_called"
    assert health_payload["analytics_status"] == "unavailable"
    assert health_payload["cache_status"] == "missing"
    assert health_payload["cache_fetched_at_utc"] is None
    assert health_payload["openapi_url"] == "/openapi.json"
    assert health_payload["elexon_base_url"] == "https://data.elexon.co.uk/bmrs/api/v1"
    assert "generation" not in health_payload
    assert "publishTime" not in health_payload
    assert "startTime" not in health_payload
    alias_response = client.get("/api/health")
    assert alias_response.status_code == 200
    assert alias_response.json() == health_payload


def test_health_does_not_open_a_network_connection(monkeypatch) -> None:
    def fail_if_a_connection_is_opened(*args, **kwargs):
        del args, kwargs
        raise AssertionError("The health check tried to open a network connection.")

    monkeypatch.setattr(socket, "create_connection", fail_if_a_connection_is_opened)
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["elexon_request_status"] == "not_called"


def test_allowed_browser_origin_receives_an_explicit_cors_header() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unlisted_browser_origin_is_not_echoed() -> None:
    application_settings = Settings(
        cors_allowed_origins="http://localhost:5173",
    )
    client = TestClient(create_app(application_settings))

    response = client.get(
        "/api/health",
        headers={"Origin": "https://unknown.example"},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_unknown_path_explains_where_health_lives() -> None:
    client = TestClient(create_app())

    response = client.get("/api/forecast")

    assert response.status_code == 404
    error_payload = response.json()
    assert error_payload["error_code"] == "http_error"
    assert "GET /api/health" in error_payload["detail"]
