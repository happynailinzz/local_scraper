#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


_TZ = ZoneInfo("Asia/Shanghai")


def _extract_label(keyword_regex: str) -> str | None:
    text = (keyword_regex or "").strip()
    if not text:
        return None

    inner = text
    if text.startswith("(") and text.endswith(")") and len(text) >= 2:
        inner = text[1:-1]

    parts = [p.strip() for p in inner.split("|") if p.strip()]
    if not parts:
        return text

    cleaned: list[str] = []
    for part in parts:
        cleaned.append(re.sub(r"\\(.)", r"\1", part))

    if len(cleaned) == 1 and cleaned[0] == text:
        return text
    return ",".join(cleaned)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill KEYWORDS_LABEL in tasks")
    parser.add_argument("--db-path", default="data/zhaocai.db")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT task_id, config_json FROM tasks")
    rows = cur.fetchall()

    now = datetime.now(tz=_TZ).isoformat(timespec="seconds")
    updated = 0
    for row in rows:
        task_id = row["task_id"]
        config_raw = row["config_json"] or "{}"
        try:
            config = json.loads(config_raw)
        except Exception:
            config = {}

        if config.get("KEYWORDS_LABEL"):
            continue

        keyword_regex = str(config.get("KEYWORD_REGEX") or "").strip()
        label = _extract_label(keyword_regex)
        if not label:
            continue

        config["KEYWORDS_LABEL"] = label
        cur.execute(
            "UPDATE tasks SET config_json = ?, updated_at = ? WHERE task_id = ?",
            (json.dumps(config, ensure_ascii=False), now, task_id),
        )
        updated += 1

    conn.commit()
    conn.close()
    print(f"updated_tasks={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
