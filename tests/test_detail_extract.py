from __future__ import annotations

from pathlib import Path

from local_scraper.parser import extract_detail_content


def test_extract_detail_content_from_content_class() -> None:
    html = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "sample_detail_content_class.html"
    ).read_text(encoding="utf-8")
    content = extract_detail_content(html)
    assert "预算金额" in content
    assert "发布时间" in content
