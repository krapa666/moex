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
