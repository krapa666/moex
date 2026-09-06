from pathlib import Path

from app.volume_config import VolumeSettings

ROOT = Path(__file__).resolve().parents[2]


def test_volume_schedule_env_name_matches_runtime(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_SCHEDULE_HOUR", "17")
    monkeypatch.setenv("VOLUME_SCHEDULE_MINUTES", "5,25,55")

    settings = VolumeSettings.from_env()

    assert settings.schedule_hour == 17
    assert settings.schedule_minutes == (5, 25, 55)
    assert settings.schedule_label == "17:05, 17:25, 17:55"


def test_example_and_compose_use_volume_schedule_minutes_contract() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "VOLUME_SCHEDULE_MINUTES=20,35,45" in env_example
    assert "VOLUME_SCHEDULE_MINUTE=" not in env_example

    compose_entry = "VOLUME_SCHEDULE_MINUTES: ${VOLUME_SCHEDULE_MINUTES:-20,35,45}"
    assert compose.count(compose_entry) == 2
    assert "VOLUME_SCHEDULE_MINUTE:" not in compose


def test_backend_and_worker_share_forecast_source_health_configuration() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    shared_entries = [
        "ARSAGERA_ANALYST_NAME: ${ARSAGERA_ANALYST_NAME:-Арсагера}",
        "ARSAGERA_SYNC_INTERVAL_HOURS: ${ARSAGERA_SYNC_INTERVAL_HOURS:-6}",
        "FORECAST_SHEETS_SOURCES_JSON: ${FORECAST_SHEETS_SOURCES_JSON:-[]}",
        "FORECAST_SHEETS_SYNC_INTERVAL_HOURS: ${FORECAST_SHEETS_SYNC_INTERVAL_HOURS:-6}",
        "DOHOD_ENABLED: ${DOHOD_ENABLED:-true}",
        "DOHOD_ANALYST_NAME: ${DOHOD_ANALYST_NAME:-ДОХОДЪ}",
        "DOHOD_SYNC_INTERVAL_HOURS: ${DOHOD_SYNC_INTERVAL_HOURS:-6}",
        "FINVISTA_ENABLED: ${FINVISTA_ENABLED:-false}",
        'FINVISTA_ANALYST_NAME: "${FINVISTA_ANALYST_NAME:-fin-vista (модель)}"',
        "FINVISTA_SYNC_INTERVAL_HOURS: ${FINVISTA_SYNC_INTERVAL_HOURS:-6}",
    ]
    for entry in shared_entries:
        assert compose.count(entry) == 2

    assert "MOEX_CCI_PASSWORD: ${MOEX_CCI_PASSWORD:?" not in compose
