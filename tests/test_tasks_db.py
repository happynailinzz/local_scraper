from __future__ import annotations

from pathlib import Path
import tempfile

from local_scraper.db import Database


def test_tasks_crud() -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "zhaocai.db")
        db = Database(db_path)
        db.init_schema()

        task_id = "t1"
        db.upsert_task(
            task_id=task_id,
            name="demo",
            enabled=True,
            schedule_type="cron",
            cron_expr="0 8 * * *",
            interval_seconds=None,
            config={"DAYS_LOOKBACK": 7},
        )

        tasks = db.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == task_id

        t = db.get_task(task_id)
        assert t
        assert t["enabled"] is True
        assert t["schedule_type"] == "cron"
        assert isinstance(t.get("config"), dict)

        db.set_task_enabled(task_id, False)
        t2 = db.get_task(task_id)
        assert t2
        assert t2["enabled"] is False

        db.delete_task(task_id)
        assert db.get_task(task_id) is None

        db.close()


def test_scrape_targets_crud_and_task_binding() -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "zhaocai.db")
        db = Database(db_path)
        db.init_schema()

        task_id = "t-scrape"
        db.upsert_task(
            task_id=task_id,
            name="scrape-demo",
            enabled=True,
            schedule_type="cron",
            cron_expr="0 8 * * *",
            interval_seconds=None,
            config={"DAYS_LOOKBACK": 7},
        )

        target_id = db.create_scrape_target(
            name="中国政府采购网",
            list_url="http://www.ccgp.gov.cn/",
            base_url="http://www.ccgp.gov.cn/",
            keyword_regex="(采购|招标)",
            days_lookback=3,
            max_pages_total=80,
            max_pages_per_category=20,
            enabled=True,
        )

        target = db.get_scrape_target(target_id)
        assert target
        assert target["name"] == "中国政府采购网"
        assert target["enabled"] is True

        db.set_task_scrape_targets(task_id, [target_id])
        selected_ids = db.get_task_scrape_target_ids(task_id)
        assert selected_ids == [target_id]

        targets = db.get_task_scrape_targets(task_id)
        assert len(targets) == 1
        assert targets[0]["target_id"] == target_id
        assert targets[0]["days_lookback"] == 3

        db.set_scrape_target_enabled(target_id, False)
        disabled = db.get_scrape_target(target_id)
        assert disabled
        assert disabled["enabled"] is False
        assert db.get_task_scrape_targets(task_id) == []

        db.delete_scrape_target(target_id)
        assert db.get_scrape_target(target_id) is None
        assert db.get_task_scrape_target_ids(task_id) == []

        db.close()


def test_task_update_preserves_latest_config_and_bindings() -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "zhaocai.db")
        db = Database(db_path)
        db.init_schema()

        task_id = "t-edit"
        scrape_target_id = db.create_scrape_target(
            name="站点A",
            list_url="https://a.example.com/list",
            base_url="https://a.example.com",
        )
        feishu_target_id = db.create_feishu_target(
            name="群A",
            webhook_url="https://open.feishu.cn/hook/a",
        )

        db.upsert_task(
            task_id=task_id,
            name="old",
            enabled=True,
            schedule_type="cron",
            cron_expr="0 8 * * *",
            interval_seconds=None,
            config={"DAYS_LOOKBACK": 7},
        )
        db.set_task_scrape_targets(task_id, [scrape_target_id])
        db.set_task_targets(task_id, [feishu_target_id])

        db.upsert_task(
            task_id=task_id,
            name="new",
            enabled=False,
            schedule_type="interval",
            cron_expr=None,
            interval_seconds=1800,
            config={"DAYS_LOOKBACK": 3, "KEYWORDS_LABEL": "软件"},
        )

        task = db.get_task(task_id)
        assert task
        assert task["name"] == "new"
        assert task["enabled"] is False
        assert task["schedule_type"] == "interval"
        assert task["interval_seconds"] == 1800
        assert task["config"]["DAYS_LOOKBACK"] == 3
        assert db.get_task_scrape_target_ids(task_id) == [scrape_target_id]
        assert db.get_task_target_ids(task_id) == [feishu_target_id]

        db.close()


def test_runs_store_task_and_target_metadata() -> None:
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "zhaocai.db")
        db = Database(db_path)
        db.init_schema()

        run = db.start_run(
            run_id_override="run-meta-1",
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

        total, rows = db.list_runs()
        assert total == 1
        assert rows[0]["task_id"] == "task-1"
        assert rows[0]["task_name"] == "每日采购"
        assert rows[0]["scrape_target_names"] == ["站点A", "站点B"]
        assert rows[0]["feishu_target_names"] == ["群A"]

        row = db.get_run("run-meta-1")
        assert row
        assert row["task_id"] == "task-1"
        assert row["task_name"] == "每日采购"
        assert row["scrape_target_names"] == ["站点A", "站点B"]
        assert row["feishu_target_names"] == ["群A"]

        db.close()
