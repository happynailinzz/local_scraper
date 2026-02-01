from __future__ import annotations

from pathlib import Path

from local_scraper.parser import parse_list_page


def test_parse_list_page_fixture() -> None:
    html = (
        Path(__file__).resolve().parent / "fixtures" / "sample_list.html"
    ).read_text(encoding="utf-8")
    items = parse_list_page(html)
    assert len(items) == 5
    assert items[0].title
    assert items[0].link.startswith("/")
    assert "2026" in items[0].date_raw
