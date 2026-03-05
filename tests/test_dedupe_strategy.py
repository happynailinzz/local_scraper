from __future__ import annotations

from pathlib import Path
import tempfile

from local_scraper.db import Database


def test_dedupe_title_date_allows_same_title_different_date() -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "zhaocai.db")
        db = Database(db_path, dedupe_strategy="title_date")
        db.init_schema()

        ok1 = db.insert_announcement_base(
            target_key="",
            title="same title",
            url="http://example.com/a",
            date="2026-01-30",
            status="NEW",
        )
        ok2 = db.insert_announcement_base(
            target_key="",
            title="same title",
            url="http://example.com/b",
            date="2026-01-31",
            status="NEW",
        )
        assert ok1 is True
        assert ok2 is True

        db.close()


def test_dedupe_isolation_by_target_key() -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "zhaocai.db")
        db = Database(db_path, dedupe_strategy="title")
        db.init_schema()

        ok1 = db.insert_announcement_base(
            target_key="shiying",
            title="same title",
            url="http://example.com/a",
            date="2026-01-30",
            status="NEW",
        )
        ok2 = db.insert_announcement_base(
            target_key="taneng",
            title="same title",
            url="http://example.com/a",
            date="2026-01-30",
            status="NEW",
        )
        assert ok1 is True
        assert ok2 is True

        db.close()
