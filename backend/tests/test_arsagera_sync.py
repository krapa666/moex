from datetime import datetime, timezone

from app.arsagera_sync import _merge_future_values


def test_merge_future_values_updates_only_current_and_future_years() -> None:
    current_year = datetime.now(timezone.utc).year
    existing = {
        str(current_year - 1): 100.0,
        str(current_year): 110.0,
        str(current_year + 1): 120.0,
    }
    incoming = {
        str(current_year - 1): 999.0,
        str(current_year): 111.0,
        str(current_year + 1): 121.0,
        str(current_year + 2): 130.0,
    }

    merged, changed = _merge_future_values(existing, incoming)

    assert changed is True
    assert merged[str(current_year - 1)] == 100.0
    assert merged[str(current_year)] == 111.0
    assert merged[str(current_year + 1)] == 121.0
    assert merged[str(current_year + 2)] == 130.0


def test_merge_future_values_is_idempotent() -> None:
    current_year = datetime.now(timezone.utc).year
    existing = {str(current_year): 111.0, str(current_year + 1): 121.0}

    merged, changed = _merge_future_values(existing, dict(existing))

    assert changed is False
    assert merged == existing
