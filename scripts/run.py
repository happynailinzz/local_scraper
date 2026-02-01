#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))

    parser = argparse.ArgumentParser(description="local_scraper: run once")
    parser.add_argument("--db-path", help="SQLite DB path")
    parser.add_argument(
        "--dry-run", action="store_true", help="Skip detail fetch + AI + Feishu"
    )
    parser.add_argument(
        "--ai-disabled", action="store_true", help="Disable AI calls (fallback summary)"
    )
    parser.add_argument(
        "--use-test-fixtures", action="store_true", help="Use local HTML fixtures"
    )
    parser.add_argument(
        "--max-items", type=int, help="Max items per run (0 = unlimited)"
    )
    parser.add_argument(
        "--max-pages-total",
        type=int,
        help="Max pages to fetch across categories (default: 200)",
    )
    parser.add_argument(
        "--max-pages-per-category",
        type=int,
        help="Max pages to fetch per category (default: 50)",
    )
    parser.add_argument("--loop-delay", type=float, help="Delay seconds between items")
    parser.add_argument("--days-lookback", type=int, help="Look back N days")
    parser.add_argument(
        "--keyword-regex",
        help="Override keyword regex (example: (系统|软件|平台))",
    )
    parser.add_argument(
        "--keywords",
        help="Comma-separated keywords (will be converted to regex OR)",
    )
    parser.add_argument("--log-json", action="store_true", help="Output logs as JSON")
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warn", "error"],
        help="Log level (default: info)",
    )
    parser.add_argument(
        "--dedupe-strategy",
        choices=["title", "url", "title_date"],
        help="Dedupe strategy (default: title)",
    )
    args = parser.parse_args()

    if args.db_path:
        os.environ["DB_PATH"] = args.db_path
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    if args.ai_disabled:
        os.environ["AI_DISABLED"] = "true"
    if args.use_test_fixtures:
        os.environ["USE_TEST_FIXTURES"] = "true"
    if args.max_items is not None:
        os.environ["MAX_ITEMS_PER_RUN"] = str(args.max_items)
    if args.max_pages_total is not None:
        os.environ["MAX_PAGES_TOTAL"] = str(args.max_pages_total)
    if args.max_pages_per_category is not None:
        os.environ["MAX_PAGES_PER_CATEGORY"] = str(args.max_pages_per_category)
    if args.loop_delay is not None:
        os.environ["LOOP_DELAY"] = str(args.loop_delay)
    if args.days_lookback is not None:
        os.environ["DAYS_LOOKBACK"] = str(args.days_lookback)
    if args.keyword_regex:
        os.environ["KEYWORD_REGEX"] = args.keyword_regex
        os.environ["KEYWORDS_LABEL"] = args.keyword_regex
    if args.keywords:
        parts = [p.strip() for p in args.keywords.split(",") if p.strip()]
        if parts:
            import re

            os.environ["KEYWORD_REGEX"] = (
                "(" + "|".join(re.escape(p) for p in parts) + ")"
            )
            os.environ["KEYWORDS_LABEL"] = ",".join(parts)
    if args.log_json:
        os.environ["LOG_JSON"] = "true"
    if args.log_level:
        os.environ["LOG_LEVEL"] = args.log_level
    if args.dedupe_strategy:
        os.environ["DEDUPE_STRATEGY"] = args.dedupe_strategy

    project_dir = Path(__file__).resolve().parents[1]
    src_dir = project_dir / "src"
    sys.path.insert(0, str(src_dir))

    from local_scraper.config import Config
    from local_scraper.workflow import run_once

    cfg = Config.from_env()
    report = run_once(cfg)

    print("========================================")
    print("[report]")
    for k in (
        "run_id",
        "execution_time",
        "duration_seconds",
        "total_processed",
        "total_new",
        "total_duplicate",
    ):
        print(f"{k}: {report.get(k)}")
    print("========================================")
    return 0 if report.get("status") == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
