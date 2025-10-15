import importlib
from pathlib import Path


def test_parse_listings(app_env):
    scraper = importlib.reload(importlib.import_module("scraper"))

    sample_html = Path("tests/fixtures/sample_list.html").read_text(encoding="utf-8")
    listings = scraper.parse_listings(sample_html, "https://example.com/base")

    assert len(listings) == 2
    first = listings[0]
    assert first.post_id == "101"
    assert first.title == "Bright Studio"
    assert first.price == "$1,800"
    assert first.neighborhood == "Downtown"
    assert first.url == "https://example.com/listings/101"

    second = listings[1]
    assert second.post_id == "102"
    assert second.title == "Cozy Loft"
    assert second.price is None
    assert second.neighborhood == "Mission"
    assert second.url == "https://example.com/listings/102"

