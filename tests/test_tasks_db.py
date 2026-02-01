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
