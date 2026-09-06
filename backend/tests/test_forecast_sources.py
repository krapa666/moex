import pytest
from app.forecast_sources import (
    PublishedSheetsClient,
    load_published_sheets_sources,
    parse_published_catalog_gids,
)


def test_load_published_sheets_sources_normalizes_aliases() -> None:
    sources = load_published_sheets_sources(
        '[{"analyst_name":"Demo","published_id":"2PACX-demo","catalog_gid":"123",'
        '"sheet_aliases":{"pref":"base"}}]'
    )

    assert len(sources) == 1
    assert sources[0].analyst_name == "Demo"
    assert sources[0].sheet_aliases == {"PREF": "BASE"}


def test_load_published_sheets_sources_rejects_duplicate_analyst_names() -> None:
    raw = (
        '[{"analyst_name":"Demo","published_id":"one","catalog_gid":"1"},'
        '{"analyst_name":"demo","published_id":"two","catalog_gid":"2"}]'
    )

    with pytest.raises(ValueError, match="duplicate analyst_name"):
        load_published_sheets_sources(raw)


def test_generic_catalog_does_not_apply_arsagera_specific_aliases() -> None:
    html = """
    <script>
    var items = [];
    items.push({name: "Каталог", pageUrl: "...gid=999", gid: "999",initialSheet: true});
    items.push({name: "SNGSP", pageUrl: "...gid=111", gid: "111"});
    items.push({name: "SNGS", pageUrl: "...gid=222", gid: "222"});
    </script>
    """

    mapping, errors = parse_published_catalog_gids(html, ["SNGSP"], catalog_gid="999")

    assert mapping == {"SNGSP": "111"}
    assert errors == {}


@pytest.mark.asyncio
async def test_published_sheets_client_maps_alias_to_sheet_gid(monkeypatch) -> None:
    client = PublishedSheetsClient(
        published_id="2PACX-demo",
        catalog_gid="999",
        sheet_aliases={"PREF": "BASE"},
    )
    html = """
    <script>
    var items = [];
    items.push({name: "Каталог", pageUrl: "...gid=999", gid: "999",initialSheet: true});
    items.push({name: "BASE", pageUrl: "...gid=12345", gid: "12345"});
    </script>
    """

    async def fake_get_text(url: str) -> str:
        assert url.endswith("/pubhtml?gid=999")
        return html

    monkeypatch.setattr(client, "_get_text", fake_get_text)

    mapping, errors = await client.fetch_catalog_mapping(["PREF"])

    assert mapping == {"PREF": "12345"}
    assert errors == {}
