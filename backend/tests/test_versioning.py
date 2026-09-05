from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SEMVER_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def test_repository_version_is_semver_and_has_matching_release_notes() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert SEMVER_RE.fullmatch(version)
    assert (ROOT / ".release" / f"v{version}.md").is_file()
