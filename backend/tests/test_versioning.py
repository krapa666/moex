import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_repository_version_is_semver_and_has_matching_release_notes() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert re.fullmatch(r"0|[1-9]\d*\.0|[1-9]\d*\.[1-9]\d*|0\.[1-9]\d*\.0|0\.[1-9]\d*\.[1-9]\d*|[1-9]\d*\.[1-9]\d*\.0|[1-9]\d*\.[1-9]\d*\.[1-9]\d*", version)
    assert (ROOT / ".release" / f"v{version}.md").is_file()
