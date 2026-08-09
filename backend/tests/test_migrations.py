import re
from pathlib import Path

REVISION_PATTERN = re.compile(
    r'^revision(?:\s*:\s*\w+)?\s*=\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)


def test_alembic_revision_ids_fit_default_version_column() -> None:
    versions_dir = Path(__file__).parents[1] / "alembic" / "versions"
    revisions: dict[str, Path] = {}

    for path in versions_dir.glob("*.py"):
        match = REVISION_PATTERN.search(path.read_text(encoding="utf-8"))
        assert match is not None, f"Migration {path.name} has no revision ID"
        revision = match.group(1)
        assert len(revision) <= 32, (
            f"Migration {path.name} revision ID is {len(revision)} characters; "
            "Alembic's default version_num column allows 32"
        )
        assert revision not in revisions, (
            f"Migration {path.name} duplicates revision from {revisions[revision].name}"
        )
        revisions[revision] = path
