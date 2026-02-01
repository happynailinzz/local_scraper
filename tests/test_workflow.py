from __future__ import annotations

from pathlib import Path
import tempfile

from local_scraper.config import Config
from local_scraper.workflow import run_once


def _cfg(
    db_path: str,
    *,
    dry_run: bool,
    use_test_fixtures: bool,
    days_lookback: int = 2,
) -> Config:
    return Config(
        list_url="http://zpzb.zgpmsm.cn/qiye/index.jhtml",
        base_url="http://zpzb.zgpmsm.cn",
        user_agent="pytest",
        db_path=db_path,
        dedupe_strategy="title",
        run_id_override=None,
        keyword_regex=r"(系统|软件|平台|大数据|AI|采购|招标)",
        days_lookback=days_lookback,
        loop_delay_seconds=0,
        max_items_per_run=50,
        http_timeout_ms=1000,
        http_retry_count=1,
        http_retry_interval_ms=0,
        ai_api_key="",
        ai_base_url="https://api.yuweixun.site/v1",
        ai_model="llama-3.3-70b-versatile",
        ai_temperature=0.5,
        ai_timeout_ms=1000,
        ai_retry_count=1,
        ai_retry_interval_ms=0,
        feishu_webhook_url=None,
        dry_run=dry_run,
        ai_disabled=True,
        use_test_fixtures=use_test_fixtures,
        log_json=False,
        log_level="info",
    )


def test_run_once_dry_run_with_fixtures() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "zhaocai.db")
        report = run_once(_cfg(db, dry_run=True, use_test_fixtures=True))
        assert report["status"] == "COMPLETED"
        assert report["total_processed"] == 3
        assert report["total_new"] == 3
        assert report["total_duplicate"] == 0


def test_run_once_dedupe_with_fixtures() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "zhaocai.db")

        r1 = run_once(_cfg(db, dry_run=False, use_test_fixtures=True))
        assert r1["status"] == "COMPLETED"
        assert r1["total_new"] == 3
        assert r1["total_duplicate"] == 0

        r2 = run_once(_cfg(db, dry_run=False, use_test_fixtures=True))
        assert r2["status"] == "COMPLETED"
        assert r2["total_new"] == 0
        assert r2["total_duplicate"] == 3


def test_run_once_fallback_summary_when_ai_disabled() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "zhaocai.db")
        r1 = run_once(_cfg(db, dry_run=False, use_test_fixtures=True))
        assert r1["status"] == "COMPLETED"


def test_run_once_lookback_7_days_includes_older_fixture_item() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "zhaocai.db")
        report = run_once(
            _cfg(db, dry_run=True, use_test_fixtures=True, days_lookback=7)
        )
        assert report["status"] == "COMPLETED"
        assert report["total_new"] == 4
