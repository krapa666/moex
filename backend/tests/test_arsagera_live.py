import pytest
from app.arsagera_source import ARSAGERA_BASE_URL, ArsageraClient


@pytest.mark.asyncio
async def test_live_arsagera_sber_diagnostics() -> None:
    client = ArsageraClient(timeout_seconds=30.0)
    gid = "1342158761"
    content = await client._get_text(
        f"{ARSAGERA_BASE_URL}/pub?gid={gid}&single=true&output=csv"
    )
    lines = content.splitlines()
    for index, line in enumerate(lines):
        lower = line.lower()
        if "чист" in lower or "дивид" in lower:
            start = max(0, index - 3)
            end = min(len(lines), index + 4)
            print("ARSAGERA_CSV_DIAG", index, " || ".join(lines[start:end]))
    assert False, "diagnostic run"
