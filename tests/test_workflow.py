from __future__ import annotations

from pathlib import Path
import tempfile
import json

from local_scraper.config import Config
from local_scraper.workflow import run_once
from local_scraper.workflow import _load_site_targets
from local_scraper.workflow import _normalize_site_entry


def _cfg(
    db_path: str,
    *,
    dry_run: bool,
    use_test_fixtures: bool,
    days_lookback: int = 2,
    site_list_markdown_path: str | None = None,
) -> Config:
    return Config(
        list_url="http://zpzb.zgpmsm.cn/qiye/index.jhtml",
        base_url="http://zpzb.zgpmsm.cn",
        site_list_markdown_path=site_list_markdown_path,
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


def test_run_once_reads_site_list_markdown_with_fixtures() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "zhaocai.db")
        md = Path(td) / "sites.md"
        md.write_text(
            "\n".join(
                [
                    "| 名称 | 官网主页 |",
                    "| --- | --- |",
                    "| 站点A | [https://a.example.com](https://a.example.com) |",
                    "| 站点B | [https://b.example.com](https://b.example.com) |",
                ]
            ),
            encoding="utf-8",
        )

        report = run_once(
            _cfg(
                db,
                dry_run=True,
                use_test_fixtures=True,
                site_list_markdown_path=str(md),
            )
        )
        assert report["status"] == "COMPLETED"
        assert report["total_processed"] == 6
        assert report["total_new"] == 6


def test_load_site_targets_keeps_chinabidding_cc_domain() -> None:
    with tempfile.TemporaryDirectory() as td:
        md = Path(td) / "sites.md"
        md.write_text(
            "\n".join(
                [
                    "| 名称 | 官网主页 |",
                    "| --- | --- |",
                    "| 中国采购与招标网 | [http://www.chinabidding.cc/](http://www.chinabidding.cc/) |",
                ]
            ),
            encoding="utf-8",
        )
        cfg = _cfg(
            str(Path(td) / "db.sqlite"),
            dry_run=True,
            use_test_fixtures=True,
            site_list_markdown_path=str(md),
        )

        targets = _load_site_targets(cfg)

        assert targets[0].list_url == "http://www.chinabidding.cc/"


def test_normalize_henan_public_resource_entry() -> None:
    list_url, base_url = _normalize_site_entry(
        "河南省公共资源交易中心", "http://www.hnggzy.com/hnsggzy/"
    )
    assert list_url == "http://hnsggzyjy.henan.gov.cn/"
    assert base_url == "http://hnsggzyjy.henan.gov.cn/"


def test_normalize_zcpt_entry() -> None:
    list_url, base_url = _normalize_site_entry(
        "中国平煤神马集团智采平台", "http://zcpt.zgpmsm.com.cn/"
    )
    assert list_url == "https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html"
    assert base_url == "https://zcpt.zgpmsm.com.cn"


def test_load_site_targets_uses_run_scrape_targets_json(monkeypatch) -> None:
    cfg = _cfg("/tmp/test.db", dry_run=True, use_test_fixtures=True)
    monkeypatch.setenv(
        "RUN_SCRAPE_TARGETS_JSON",
        json.dumps(
            [
                {
                    "name": "站点A",
                    "list_url": "https://a.example.com/list",
                    "base_url": "https://a.example.com",
                },
                {
                    "name": "站点B",
                    "list_url": "https://b.example.com/list",
                    "base_url": "https://b.example.com",
                },
            ],
            ensure_ascii=False,
        ),
    )

    targets = _load_site_targets(cfg)

    assert [t.name for t in targets] == ["站点A", "站点B"]
    assert [t.list_url for t in targets] == [
        "https://a.example.com/list",
        "https://b.example.com/list",
    ]
