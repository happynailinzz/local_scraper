from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import Config
from ..db import Database


_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class TaskRuntime:
    task_id: str
    running: bool
    last_status: str
    last_started_at: float | None
    last_finished_at: float | None
    last_exit_code: int | None
    lines: list[str]
    proc: subprocess.Popen[str] | None


class TaskScheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scheduler = BackgroundScheduler(timezone=_TZ)
        self._runtime: dict[str, TaskRuntime] = {}

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def sync_from_db(self) -> None:
        cfg = Config.from_env()
        db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
        db.init_schema()
        tasks = db.list_tasks()
        db.close()

        existing = {j.id for j in self._scheduler.get_jobs()}
        desired: set[str] = set()

        for t in tasks:
            task_id = str(t["task_id"])
            enabled = bool(t["enabled"])
            if not enabled:
                continue

            schedule_type = str(t["schedule_type"])
            cron_expr = t.get("cron_expr")
            interval_seconds = t.get("interval_seconds")

            trigger = None
            if schedule_type == "cron" and cron_expr:
                try:
                    trigger = CronTrigger.from_crontab(str(cron_expr), timezone=_TZ)
                except Exception:
                    continue
            elif schedule_type == "interval" and interval_seconds is not None:
                try:
                    seconds = int(str(interval_seconds))
                    if seconds <= 0:
                        raise ValueError("interval_seconds must be positive")
                    trigger = IntervalTrigger(seconds=seconds, timezone=_TZ)
                except Exception:
                    continue
            else:
                continue

            desired.add(task_id)
            if task_id in existing:
                continue

            try:
                self._scheduler.add_job(
                    func=self._run_task_job,
                    trigger=trigger,
                    id=task_id,
                    name=str(t["name"]),
                    replace_existing=True,
                    coalesce=True,
                    max_instances=1,
                    misfire_grace_time=60,
                )
            except Exception:
                continue

        # Remove jobs no longer enabled.
        for job_id in existing:
            if job_id not in desired:
                try:
                    self._scheduler.remove_job(job_id)
                except Exception:
                    pass

    def list_runtime(self) -> dict[str, TaskRuntime]:
        with self._lock:
            return dict(self._runtime)

    def get_runtime(self, task_id: str) -> TaskRuntime | None:
        with self._lock:
            return self._runtime.get(task_id)

    def stop(self, task_id: str) -> bool:
        with self._lock:
            rt = self._runtime.get(task_id)
            if not rt or not rt.proc or not rt.running:
                return False
            proc = rt.proc
        try:
            proc.terminate()
            return True
        except Exception:
            return False

    def run_now(self, task_id: str) -> None:
        threading.Thread(
            target=self._run_task_job, args=(task_id,), daemon=True
        ).start()

    def _run_task_job(self, task_id: str) -> None:
        cfg = Config.from_env()
        db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
        t = db.get_task(task_id)
        db.close()
        if not t:
            return

        overrides: dict[str, str] = {}
        conf_raw = t.get("config")
        conf: dict[str, object] = conf_raw if isinstance(conf_raw, dict) else {}
        for k, v in conf.items():
            overrides[str(k)] = str(v)

        env = os.environ.copy()
        env.update(overrides)
        env["LOG_JSON"] = "true"
        env["LOG_LEVEL"] = env.get("LOG_LEVEL", "info")

        cmd = [sys.executable, "scripts/run.py", "--log-json"]
        cwd = str(Path(__file__).resolve().parents[3])

        with self._lock:
            rt = self._runtime.get(task_id)
            if not rt:
                rt = TaskRuntime(
                    task_id=task_id,
                    running=False,
                    last_status="NEVER",
                    last_started_at=None,
                    last_finished_at=None,
                    last_exit_code=None,
                    lines=[],
                    proc=None,
                )
                self._runtime[task_id] = rt
            if rt.running:
                rt.lines.append("[scheduler] task already running, skip")
                return
            rt.running = True
            rt.last_status = "RUNNING"
            rt.last_started_at = time.time()
            rt.last_finished_at = None
            rt.last_exit_code = None
            rt.lines.append("[scheduler] start")

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
        except Exception as e:
            with self._lock:
                rt.running = False
                rt.last_status = "FAILED"
                rt.last_finished_at = time.time()
                rt.lines.append(f"[scheduler] failed to start: {e}")
            return

        with self._lock:
            rt.proc = proc

        assert proc.stdout is not None
        for line in proc.stdout:
            self._append_line(task_id, line.rstrip("\n"))
        code = proc.wait()

        with self._lock:
            rt.running = False
            rt.proc = None
            rt.last_finished_at = time.time()
            rt.last_exit_code = int(code)
            rt.last_status = "COMPLETED" if code == 0 else "FAILED"
            rt.lines.append(f"[scheduler] done: {rt.last_status} (code={code})")

    def _append_line(self, task_id: str, line: str) -> None:
        with self._lock:
            rt = self._runtime.get(task_id)
            if not rt:
                return
            rt.lines.append(line)
            if len(rt.lines) > 2000:
                rt.lines = rt.lines[-2000:]
