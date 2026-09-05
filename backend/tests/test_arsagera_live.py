import pytest
from app.arsagera_source import ARSAGERA_BASE_URL, ARSAGERA_CATALOG_GID, ArsageraClient


@pytest.mark.asyncio
async def test_live_arsagera_catalog_diagnostics() -> None:
    client = ArsageraClient(timeout_seconds=30.0)
    urls = {
        "single": f"{ARSAGERA_BASE_URL}/pubhtml?gid={ARSAGERA_CATALOG_GID}&single=true",
        "all": f"{ARSAGERA_BASE_URL}/pubhtml?gid={ARSAGERA_CATALOG_GID}",
    }
    for mode, url in urls.items():
        html = await client._get_text(url)
        upper = html.upper()
        print("ARSAGERA_DIAG", mode, "length", len(html))
        for needle in ("SBER", "СБЕР", "GID=", "SHEET-MENU", "SHEET-BUTTON"):
            position = upper.find(needle.upper())
            start = max(0, position - 700)
            end = min(len(html), position + 1800) if position >= 0 else 0
            snippet = html[start:end].replace("\n", " ") if position >= 0 else "NOT_FOUND"
            print("ARSAGERA_DIAG", mode, needle, position, snippet)
    assert False, "diagnostic run"
