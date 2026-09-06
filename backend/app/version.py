from pathlib import Path

PACKAGED_VERSION = "0.15.0"


def resolve_app_version() -> str:
    """Return repository VERSION in a source checkout, packaged fallback in the image."""
    repository_version = Path(__file__).resolve().parents[2] / "VERSION"
    if repository_version.is_file():
        value = repository_version.read_text(encoding="utf-8").strip()
        if value:
            return value
    return PACKAGED_VERSION


APP_VERSION = resolve_app_version()
