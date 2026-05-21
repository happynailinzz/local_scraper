from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from local_scraper.config import Config
from local_scraper.db import Database
from local_scraper.web import app as web_app
from local_scraper.web.app import app


def _auth() -> tuple[str, str]:
    cfg = Config.from_env()
    return cfg.webui_username, cfg.webui_password


def test_scrape_targets_page_and_task_detail(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    scrape_target_id = db.create_scrape_target(
        name="中国政府采购网",
        list_url="http://www.ccgp.gov.cn/",
        base_url="http://www.ccgp.gov.cn/",
        keyword_regex="(采购|招标)",
        enabled=True,
    )
    task_id = "task-1"
    db.upsert_task(
        task_id=task_id,
        name="demo",
        enabled=True,
        schedule_type="cron",
        cron_expr="0 8 * * *",
        interval_seconds=None,
        config={"DAYS_LOOKBACK": 7},
    )
    db.set_task_scrape_targets(task_id, [scrape_target_id])
    db.close()

    client = TestClient(app)

    resp = client.get("/settings/scrape-targets", auth=_auth())
    assert resp.status_code == 200
    assert "抓取站点管理" in resp.text
    assert "中国政府采购网" in resp.text

    detail = client.get(f"/tasks/{task_id}", auth=_auth())
    assert detail.status_code == 200
    assert "抓取站点" in detail.text
    assert "中国政府采购网" in detail.text


def test_scrape_target_bulk_import(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    db.close()

    client = TestClient(app)
    resp = client.post(
        "/settings/scrape-targets/import",
        auth=_auth(),
        data={
            "bulk_targets": (
                "站点A | https://a.example.com/list | https://a.example.com | (采购|招标) | 7 | 80 | 30\n"
                "站点B\thttps://b.example.com/list\thttps://b.example.com"
            )
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("imported=2")

    db = Database(db_path)
    targets = db.list_scrape_targets()
    assert len(targets) == 2
    assert targets[0]["name"] == "站点A"
    assert targets[0]["max_pages_total"] == 80
    assert targets[1]["name"] == "站点B"
    db.close()


def test_scrape_target_import_builtin_list(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    db.close()

    client = TestClient(app)
    resp = client.post(
        "/settings/scrape-targets/import-builtin",
        auth=_auth(),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "builtin_imported=" in resp.headers["location"]

    db = Database(db_path)
    targets = db.list_scrape_targets()
    names = {t["name"] for t in targets}
    assert "河南省公共资源交易中心" in names
    assert "中国平煤神马集团智采平台" in names
    db.close()


def test_task_edit_page_and_save(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    scrape_target_id = db.create_scrape_target(
        name="站点A",
        list_url="https://a.example.com/list",
        base_url="https://a.example.com",
    )
    feishu_target_id = db.create_feishu_target(
        name="群A",
        webhook_url="https://open.feishu.cn/hook/a",
    )
    task_id = "task-edit"
    db.upsert_task(
        task_id=task_id,
        name="old-task",
        enabled=True,
        schedule_type="cron",
        cron_expr="0 8 * * *",
        interval_seconds=None,
        config={"DAYS_LOOKBACK": 7, "KEYWORDS_LABEL": "采购"},
    )
    db.set_task_scrape_targets(task_id, [scrape_target_id])
    db.set_task_targets(task_id, [feishu_target_id])
    db.close()

    client = TestClient(app)

    resp = client.get(f"/tasks/{task_id}/edit", auth=_auth())
    assert resp.status_code == 200
    assert "编辑任务" in resp.text
    assert "old-task" in resp.text

    save = client.post(
        f"/tasks/{task_id}/edit",
        auth=_auth(),
        data={
            "name": "new-task",
            "enabled": "false",
            "schedule_type": "interval",
            "cron_expr": "0 8 * * *",
            "interval_seconds": "900",
            "keywords": "软件,平台",
            "days_lookback": "5",
            "dedupe_strategy": "url",
            "send_feishu": "true",
            "feishu_notify_mode": "per_item",
            "max_items": "20",
            "loop_delay": "2",
            "max_pages_total": "60",
            "max_pages_per_category": "30",
            "adaptive_threshold_pages": "6",
            "batch_size": "10",
            "delay_increment_seconds": "0.5",
            "max_loop_delay_seconds": "4",
            "scrape_target_ids": scrape_target_id,
            "feishu_target_ids": feishu_target_id,
        },
        follow_redirects=False,
    )
    assert save.status_code == 303

    db = Database(db_path)
    task = db.get_task(task_id)
    assert task
    assert task["name"] == "new-task"
    assert task["enabled"] is False
    assert task["schedule_type"] == "interval"
    assert task["interval_seconds"] == 900
    assert task["config"]["DAYS_LOOKBACK"] == 5
    assert task["config"]["DEDUPE_STRATEGY"] == "url"
    assert task["config"]["FEISHU_NOTIFY_MODE"] == "per_item"
    assert task["config"]["KEYWORDS_LABEL"] == "软件,平台"
    assert db.get_task_scrape_target_ids(task_id) == [scrape_target_id]
    assert db.get_task_target_ids(task_id) == [feishu_target_id]
    db.close()


def test_task_new_page_has_builtin_verified_shortcuts(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    db.create_scrape_target(
        name="中国平煤神马集团智采平台",
        list_url="http://zcpt.zgpmsm.com.cn/",
        base_url="http://zcpt.zgpmsm.com.cn/",
    )
    db.close()

    client = TestClient(app)
    resp = client.get("/tasks/new", auth=_auth())
    assert resp.status_code == 200
    assert "全选已验证站点" in resp.text
    assert "清空已验证站点" in resp.text


def test_tasks_page_shows_binding_counts(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    scrape_target_id = db.create_scrape_target(
        name="站点A",
        list_url="https://a.example.com/list",
        base_url="https://a.example.com",
    )
    feishu_target_id = db.create_feishu_target(
        name="群A",
        webhook_url="https://open.feishu.cn/hook/a",
    )
    task_id = "task-bindings"
    db.upsert_task(
        task_id=task_id,
        name="bind-demo",
        enabled=True,
        schedule_type="cron",
        cron_expr="0 8 * * *",
        interval_seconds=None,
        config={"DAYS_LOOKBACK": 7},
    )
    db.set_task_scrape_targets(task_id, [scrape_target_id])
    db.set_task_targets(task_id, [feishu_target_id])
    db.close()

    client = TestClient(app)
    resp = client.get("/tasks", auth=_auth())
    assert resp.status_code == 200
    assert "站点: 1" in resp.text
    assert "飞书: 1" in resp.text
    assert "站点A" in resp.text
    assert "群A" in resp.text


def test_task_copy_clones_config_and_bindings(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    scrape_target_id = db.create_scrape_target(
        name="站点A",
        list_url="https://a.example.com/list",
        base_url="https://a.example.com",
    )
    feishu_target_id = db.create_feishu_target(
        name="群A",
        webhook_url="https://open.feishu.cn/hook/a",
    )
    task_id = "task-copy"
    db.upsert_task(
        task_id=task_id,
        name="source-task",
        enabled=False,
        schedule_type="interval",
        cron_expr=None,
        interval_seconds=1200,
        config={"DAYS_LOOKBACK": 9, "KEYWORDS_LABEL": "软件"},
    )
    db.set_task_scrape_targets(task_id, [scrape_target_id])
    db.set_task_targets(task_id, [feishu_target_id])
    db.close()

    client = TestClient(app)
    resp = client.post(f"/tasks/{task_id}/copy", auth=_auth(), follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/tasks/")
    copied_task_id = location.split("/")[-1]
    assert copied_task_id != task_id

    db = Database(db_path)
    copied = db.get_task(copied_task_id)
    assert copied
    assert copied["name"] == "source-task 副本"
    assert copied["enabled"] is False
    assert copied["schedule_type"] == "interval"
    assert copied["interval_seconds"] == 1200
    assert copied["config"]["DAYS_LOOKBACK"] == 9
    assert copied["config"]["KEYWORDS_LABEL"] == "软件"
    assert db.get_task_scrape_target_ids(copied_task_id) == [scrape_target_id]
    assert db.get_task_target_ids(copied_task_id) == [feishu_target_id]
    db.close()


def test_tasks_page_has_copy_button(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    db.upsert_task(
        task_id="task-copy-button",
        name="copy-me",
        enabled=True,
        schedule_type="cron",
        cron_expr="0 8 * * *",
        interval_seconds=None,
        config={"DAYS_LOOKBACK": 7},
    )
    db.close()

    client = TestClient(app)
    resp = client.get("/tasks", auth=_auth())
    assert resp.status_code == 200
    assert "/tasks/task-copy-button/copy" in resp.text
    assert "复制" in resp.text


def test_runs_page_shows_task_and_target_bindings(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    run = db.start_run(
        run_id_override="run-bind-1",
        task_id="task-1",
        task_name="每日采购",
        scrape_target_names=["站点A", "站点B"],
        feishu_target_names=["群A"],
    )
    db.finish_run(
        run_id=run.run_id,
        status="COMPLETED",
        finished_at="2026-04-21T20:00:00+08:00",
        duration_seconds=12,
        total_processed=3,
        total_new=2,
        total_duplicate=1,
        error=None,
    )
    db.close()

    client = TestClient(app)
    resp = client.get("/runs", auth=_auth())
    assert resp.status_code == 200
    assert "关联" in resp.text
    assert "每日采购" in resp.text
    assert "站点A、站点B" in resp.text
    assert "群A" in resp.text


def test_runs_page_has_scrape_target_binding_module(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    db.create_scrape_target(
        name="中国政府采购网",
        list_url="http://www.ccgp.gov.cn/",
        base_url="http://www.ccgp.gov.cn/",
        keyword_regex="(采购|招标)",
        enabled=True,
    )
    db.close()

    client = TestClient(app)
    resp = client.get("/runs", auth=_auth())
    assert resp.status_code == 200
    assert "抓取站点（可多选，留空则使用全局 LIST_URL）" in resp.text
    assert "中国政府采购网" in resp.text
    assert "管理抓取站点" in resp.text


def test_runs_start_passes_selected_scrape_targets(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "zhaocai.db")
    monkeypatch.setenv("DB_PATH", db_path)

    db = Database(db_path)
    db.init_schema()
    target_id = db.create_scrape_target(
        name="站点A",
        list_url="https://a.example.com/list",
        base_url="https://a.example.com",
        keyword_regex="(采购|招标)",
        enabled=True,
    )
    db.close()

    captured: dict[str, object] = {}

    def fake_start(overrides: dict[str, str]) -> str:
        captured.update(overrides)
        return "run-test-1"

    monkeypatch.setattr(web_app._RUNS, "start", fake_start)

    client = TestClient(app)
    resp = client.post(
        "/runs/start",
        auth=_auth(),
        data={
            "days_lookback": "7",
            "keywords": "采购",
            "dedupe_strategy": "title",
            "max_items": "0",
            "loop_delay": "1",
            "send_feishu": "true",
            "feishu_notify_mode": "digest",
            "max_pages_total": "80",
            "max_pages_per_category": "50",
            "adaptive_threshold_pages": "10",
            "batch_size": "50",
            "delay_increment_seconds": "1",
            "max_loop_delay_seconds": "10",
            "scrape_target_ids": target_id,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/runs/run-test-1"
    assert captured["TASK_NAME"] == "WebUI 单次运行"
    assert captured["RUN_SCRAPE_TARGET_NAMES"] == "站点A"
    assert "RUN_SCRAPE_TARGETS_JSON" in captured
