from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import sqlite3
import uuid
import json


_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    started_at: str


class Database:
    def __init__(self, path: str, dedupe_strategy: str = "title"):
        self._path = path
        self._dedupe_strategy = (dedupe_strategy or "title").strip().lower()
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def list_announcements(
        self,
        *,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
        ai_summary_state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[dict[str, object]]]:
        where: list[str] = []
        params: list[object] = []

        if q:
            where.append("(title LIKE ? OR url LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
        if date_from:
            where.append("date >= ?")
            params.append(date_from)
        if date_to:
            where.append("date <= ?")
            params.append(date_to)
        if status:
            where.append("status = ?")
            params.append(status)

        if ai_summary_state:
            s = ai_summary_state.strip().lower()
            if s == "empty":
                where.append("(ai_summary IS NULL OR ai_summary = '')")
            elif s == "failed":
                where.append("ai_summary = 'AI 总结失败'")
            elif s == "ok":
                where.append(
                    "(ai_summary IS NOT NULL AND ai_summary != '' AND ai_summary != 'AI 总结失败')"
                )

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cur = self._conn.cursor()
        cur.execute(f"SELECT COUNT(1) FROM announcements {where_sql}", params)
        total = int(cur.fetchone()[0])

        cur.execute(
            f"""
            SELECT id, title, url, date, status, created_at, updated_at,
                   substr(ai_summary, 1, 160) AS ai_summary_preview
            FROM announcements
            {where_sql}
            ORDER BY date DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, int(limit), int(offset)],
        )
        rows = [dict(r) for r in cur.fetchall()]
        return total, rows

    def get_announcement(self, announcement_id: int) -> dict[str, object] | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, title, url, date, content, ai_summary, status, created_at, updated_at
            FROM announcements
            WHERE id = ?
            """,
            (announcement_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def list_runs(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[int, list[dict[str, object]]]:
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(1) FROM runs")
        total = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT run_id, started_at, finished_at, duration_seconds,
                   total_processed, total_new, total_duplicate, status, error
            FROM runs
            ORDER BY started_at DESC
            LIMIT ? OFFSET ?
            """,
            (int(limit), int(offset)),
        )
        return total, [dict(r) for r in cur.fetchall()]

    def get_run(self, run_id: str) -> dict[str, object] | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT run_id, started_at, finished_at, duration_seconds,
                   total_processed, total_new, total_duplicate, status, error
            FROM runs
            WHERE run_id = ?
            """,
            (run_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def init_schema(self) -> None:
        cur = self._conn.cursor()
        self._ensure_runs_table(cur)
        self._ensure_announcements_table(cur)
        self._ensure_tasks_table(cur)
        self._ensure_feishu_targets_table(cur)
        self._ensure_task_feishu_targets_table(cur)
        self._conn.commit()

    def _ensure_tasks_table(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              task_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              enabled INTEGER NOT NULL,
              schedule_type TEXT NOT NULL,
              cron_expr TEXT NULL,
              interval_seconds INTEGER NULL,
              config_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_enabled ON tasks(enabled)")

    def list_tasks(self) -> list[dict[str, object]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT task_id, name, enabled, schedule_type, cron_expr, interval_seconds,
                   created_at, updated_at
            FROM tasks
            ORDER BY updated_at DESC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["enabled"] = bool(r.get("enabled"))
        return rows

    def get_task(self, task_id: str) -> dict[str, object] | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT task_id, name, enabled, schedule_type, cron_expr, interval_seconds,
                   config_json, created_at, updated_at
            FROM tasks
            WHERE task_id = ?
            """,
            (task_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["enabled"] = bool(d.get("enabled"))
        try:
            d["config"] = json.loads(d.get("config_json") or "{}")
        except Exception:  # noqa: BLE001
            d["config"] = {}
        return d

    def upsert_task(
        self,
        *,
        task_id: str,
        name: str,
        enabled: bool,
        schedule_type: str,
        cron_expr: str | None,
        interval_seconds: int | None,
        config: dict[str, object],
    ) -> None:
        now = datetime.now(tz=_TZ).isoformat(timespec="seconds")
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO tasks (task_id, name, enabled, schedule_type, cron_expr, interval_seconds, config_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
              name=excluded.name,
              enabled=excluded.enabled,
              schedule_type=excluded.schedule_type,
              cron_expr=excluded.cron_expr,
              interval_seconds=excluded.interval_seconds,
              config_json=excluded.config_json,
              updated_at=excluded.updated_at
            """,
            (
                task_id,
                name,
                1 if enabled else 0,
                schedule_type,
                cron_expr,
                interval_seconds,
                json.dumps(config, ensure_ascii=False),
                now,
                now,
            ),
        )
        self._conn.commit()

    def set_task_enabled(self, task_id: str, enabled: bool) -> None:
        now = datetime.now(tz=_TZ).isoformat(timespec="seconds")
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE tasks SET enabled = ?, updated_at = ? WHERE task_id = ?",
            (1 if enabled else 0, now, task_id),
        )
        self._conn.commit()

    def delete_task(self, task_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        self._conn.commit()

    def _ensure_runs_table(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY,
              started_at TEXT NOT NULL,
              finished_at TEXT NULL,
              duration_seconds INTEGER NULL,
              total_processed INTEGER NOT NULL,
              total_new INTEGER NOT NULL,
              total_duplicate INTEGER NOT NULL,
              status TEXT NOT NULL,
              error TEXT NULL
            )
            """
        )

    def _announcements_exists(self, cur: sqlite3.Cursor) -> bool:
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='announcements' LIMIT 1"
        )
        return cur.fetchone() is not None

    def _has_unique_title_constraint(self, cur: sqlite3.Cursor) -> bool:
        # Detect UNIQUE(title) table constraint created in the original schema.
        cur.execute("PRAGMA index_list('announcements')")
        for row in cur.fetchall():
            name = row[1]
            unique = row[2]
            if not unique:
                continue
            if not str(name).startswith("sqlite_autoindex_announcements"):
                continue
            cur.execute(f"PRAGMA index_info('{name}')")
            cols = [r[2] for r in cur.fetchall()]
            if cols == ["title"]:
                return True
        return False

    def _create_common_indexes(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_announcements_date ON announcements(date)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_announcements_status ON announcements(status)"
        )

    def _create_announcements_v2(
        self, cur: sqlite3.Cursor, *, table_name: str = "announcements"
    ) -> None:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
              id INTEGER PRIMARY KEY,
              title TEXT NOT NULL,
              url TEXT NOT NULL,
              date TEXT NOT NULL,
              content TEXT NULL,
              ai_summary TEXT NULL,
              status TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'zpzb.zgpmsm.cn',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )

    def _dedupe_existing_rows(self, cur: sqlite3.Cursor) -> None:
        # Best-effort cleanup to allow unique index creation.
        if self._dedupe_strategy == "url":
            cur.execute(
                """
                DELETE FROM announcements
                WHERE id NOT IN (SELECT MIN(id) FROM announcements GROUP BY url)
                """
            )
        elif self._dedupe_strategy == "title_date":
            cur.execute(
                """
                DELETE FROM announcements
                WHERE id NOT IN (SELECT MIN(id) FROM announcements GROUP BY title, date)
                """
            )
        else:
            cur.execute(
                """
                DELETE FROM announcements
                WHERE id NOT IN (SELECT MIN(id) FROM announcements GROUP BY title)
                """
            )

    def _create_strategy_unique_index(self, cur: sqlite3.Cursor) -> None:
        # Only create the active strategy index.
        if self._dedupe_strategy == "url":
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_announcements_url ON announcements(url)"
            )
        elif self._dedupe_strategy == "title_date":
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_announcements_title_date ON announcements(title, date)"
            )
        else:
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_announcements_title ON announcements(title)"
            )

    def _migrate_v1_to_v2(self, cur: sqlite3.Cursor) -> None:
        # Rebuild announcements table to remove table-level UNIQUE(title) constraint.
        self._create_announcements_v2(cur, table_name="announcements_new")
        cur.execute(
            """
            INSERT INTO announcements_new (id, title, url, date, content, ai_summary, status, source, created_at, updated_at)
            SELECT id, title, url, date, content, ai_summary, status, source, created_at, updated_at
            FROM announcements
            """
        )
        cur.execute("DROP TABLE announcements")
        cur.execute("ALTER TABLE announcements_new RENAME TO announcements")

    def _ensure_announcements_table(self, cur: sqlite3.Cursor) -> None:
        if not self._announcements_exists(cur):
            self._create_announcements_v2(cur)
            self._create_common_indexes(cur)
            self._dedupe_existing_rows(cur)
            self._create_strategy_unique_index(cur)
            return

        if self._dedupe_strategy != "title" and self._has_unique_title_constraint(cur):
            self._migrate_v1_to_v2(cur)

        self._create_common_indexes(cur)
        self._dedupe_existing_rows(cur)
        self._create_strategy_unique_index(cur)

    def start_run(self, run_id_override: str | None = None) -> RunRecord:
        run_id = (run_id_override or "").strip() or str(uuid.uuid4())
        started_at = datetime.now(tz=_TZ).isoformat(timespec="seconds")
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO runs (run_id, started_at, total_processed, total_new, total_duplicate, status)
            VALUES (?, ?, 0, 0, 0, 'RUNNING')
            """,
            (run_id, started_at),
        )
        self._conn.commit()
        return RunRecord(run_id=run_id, started_at=started_at)

    def finish_run(
        self,
        run_id: str,
        status: str,
        finished_at: str,
        duration_seconds: int,
        total_processed: int,
        total_new: int,
        total_duplicate: int,
        error: str | None,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE runs
            SET finished_at = ?,
                duration_seconds = ?,
                total_processed = ?,
                total_new = ?,
                total_duplicate = ?,
                status = ?,
                error = ?
            WHERE run_id = ?
            """,
            (
                finished_at,
                duration_seconds,
                total_processed,
                total_new,
                total_duplicate,
                status,
                error,
                run_id,
            ),
        )
        self._conn.commit()

    def is_duplicate(self, *, title: str, url: str, date: str) -> bool:
        cur = self._conn.cursor()
        if self._dedupe_strategy == "url":
            cur.execute("SELECT 1 FROM announcements WHERE url = ? LIMIT 1", (url,))
        elif self._dedupe_strategy == "title_date":
            cur.execute(
                "SELECT 1 FROM announcements WHERE title = ? AND date = ? LIMIT 1",
                (title, date),
            )
        else:
            cur.execute("SELECT 1 FROM announcements WHERE title = ? LIMIT 1", (title,))
        return cur.fetchone() is not None

    def insert_announcement_base(
        self, title: str, url: str, date: str, status: str
    ) -> bool:
        now = datetime.now(tz=_TZ).isoformat(timespec="seconds")
        cur = self._conn.cursor()
        before = self._conn.total_changes
        cur.execute(
            """
            INSERT OR IGNORE INTO announcements (title, url, date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, url, date, status, now, now),
        )
        self._conn.commit()
        after = self._conn.total_changes
        return (after - before) > 0

    def update_announcement_detail(
        self, title: str, content: str, ai_summary: str, status: str
    ) -> None:
        now = datetime.now(tz=_TZ).isoformat(timespec="seconds")
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE announcements
            SET content = ?, ai_summary = ?, status = ?, updated_at = ?
            WHERE title = ?
            """,
            (content, ai_summary, status, now, title),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # feishu_targets                                                       #
    # ------------------------------------------------------------------ #

    def _ensure_feishu_targets_table(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS feishu_targets (
              target_id     TEXT PRIMARY KEY,
              name          TEXT NOT NULL,
              webhook_url   TEXT NOT NULL,
              keyword_regex TEXT NOT NULL DEFAULT '',
              enabled       INTEGER NOT NULL DEFAULT 1,
              created_at    TEXT NOT NULL,
              updated_at    TEXT NOT NULL
            )
            """
        )

    def _ensure_task_feishu_targets_table(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS task_feishu_targets (
              task_id   TEXT NOT NULL,
              target_id TEXT NOT NULL,
              PRIMARY KEY (task_id, target_id)
            )
            """
        )

    def list_feishu_targets(self) -> list[dict[str, object]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT target_id, name, webhook_url, keyword_regex, enabled, created_at, updated_at
            FROM feishu_targets
            ORDER BY created_at ASC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["enabled"] = bool(r.get("enabled"))
        return rows

    def get_feishu_target(self, target_id: str) -> dict[str, object] | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT target_id, name, webhook_url, keyword_regex, enabled, created_at, updated_at
            FROM feishu_targets WHERE target_id = ?
            """,
            (target_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["enabled"] = bool(d.get("enabled"))
        return d

    def create_feishu_target(
        self,
        *,
        name: str,
        webhook_url: str,
        keyword_regex: str = "",
        enabled: bool = True,
    ) -> str:
        now = datetime.now(tz=_TZ).isoformat(timespec="seconds")
        target_id = str(uuid.uuid4())
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO feishu_targets
              (target_id, name, webhook_url, keyword_regex, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (target_id, name, webhook_url, keyword_regex, 1 if enabled else 0, now, now),
        )
        self._conn.commit()
        return target_id

    def update_feishu_target(
        self,
        target_id: str,
        *,
        name: str,
        webhook_url: str,
        keyword_regex: str,
        enabled: bool,
    ) -> None:
        now = datetime.now(tz=_TZ).isoformat(timespec="seconds")
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE feishu_targets
            SET name = ?, webhook_url = ?, keyword_regex = ?, enabled = ?, updated_at = ?
            WHERE target_id = ?
            """,
            (name, webhook_url, keyword_regex, 1 if enabled else 0, now, target_id),
        )
        self._conn.commit()

    def delete_feishu_target(self, target_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM task_feishu_targets WHERE target_id = ?", (target_id,))
        cur.execute("DELETE FROM feishu_targets WHERE target_id = ?", (target_id,))
        self._conn.commit()

    def set_target_enabled(self, target_id: str, enabled: bool) -> None:
        now = datetime.now(tz=_TZ).isoformat(timespec="seconds")
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE feishu_targets SET enabled = ?, updated_at = ? WHERE target_id = ?",
            (1 if enabled else 0, now, target_id),
        )
        self._conn.commit()

    def get_task_targets(self, task_id: str) -> list[dict[str, object]]:
        """返回该任务关联的、已启用的飞书目标列表（含完整字段）。"""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT ft.target_id, ft.name, ft.webhook_url, ft.keyword_regex, ft.enabled
            FROM task_feishu_targets tft
            JOIN feishu_targets ft ON ft.target_id = tft.target_id
            WHERE tft.task_id = ? AND ft.enabled = 1
            ORDER BY ft.created_at ASC
            """,
            (task_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["enabled"] = bool(r.get("enabled"))
        return rows

    def get_task_target_ids(self, task_id: str) -> list[str]:
        """返回该任务关联的所有 target_id（含禁用项，用于表单回显）。"""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT target_id FROM task_feishu_targets WHERE task_id = ? ORDER BY rowid ASC",
            (task_id,),
        )
        return [r[0] for r in cur.fetchall()]

    def set_task_targets(self, task_id: str, target_ids: list[str]) -> None:
        """覆盖任务关联的飞书目标列表（先删后插）。"""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM task_feishu_targets WHERE task_id = ?", (task_id,))
        for tid in target_ids:
            cur.execute(
                "INSERT OR IGNORE INTO task_feishu_targets (task_id, target_id) VALUES (?, ?)",
                (task_id, tid),
            )
        self._conn.commit()
