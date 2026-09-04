from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from meta_kpi_calc.api.app import create_app
from meta_kpi_calc.core.config import Settings


def settings_for(tmp_path: Path, *, demo_mode: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=demo_mode,
        database_url=f"sqlite:///{tmp_path / 'real.db'}",
        demo_database_url=f"sqlite:///{tmp_path / 'demo.db'}",
    )


def test_health_works_without_meta_token_or_network(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Meta KPI Calculator",
        "mode": "demo",
        "database": "ok",
        "scheduler": "disabled",
    }


def test_health_reports_real_mode(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path, demo_mode=False))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["mode"] == "real"


class BrokenEngine:
    def connect(self) -> None:
        raise OperationalError("SELECT 1", {}, OSError("private/path.db"))


class BrokenDatabase:
    engine = BrokenEngine()


def test_health_database_failure_is_sanitized(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path))
    app.state.database = BrokenDatabase()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")

    body = response.text
    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "database_unavailable",
            "message": "Database health check failed",
        }
    }
    assert "private/path.db" not in body

