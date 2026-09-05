from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_repository_version_is_semver_and_has_matching_release_notes() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = version.split(".")

    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
    assert all(part == "0" or not part.startswith("0") for part in parts)
    assert (ROOT / ".release" / f"v{version}.md").is_file()
