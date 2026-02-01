#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))

    project_dir = Path(__file__).resolve().parents[1]
    src_dir = project_dir / "src"
    sys.path.insert(0, str(src_dir))

    from local_scraper.ai_client import AiClient, AiConfig
    from local_scraper.http_client import HttpClient, HttpConfig
    from local_scraper.parser import extract_detail_content

    api_key = (os.environ.get("AI_API_KEY") or "").strip()
    if not api_key:
        print("AI_API_KEY is missing; aborting")
        return 2

    fixture_path = project_dir / "tests" / "fixtures" / "sample_detail.html"
    if not fixture_path.exists():
        print(f"Fixture not found: {fixture_path}")
        return 2

    html = fixture_path.read_text(encoding="utf-8")
    content = extract_detail_content(html)
    if not content:
        print("No content extracted from fixture")
        return 2

    http = HttpClient(
        HttpConfig(
            user_agent=os.environ.get("USER_AGENT", "local_scraper"),
            timeout_ms=int(os.environ.get("AI_TIMEOUT_MS", "60000")),
            retry_count=int(os.environ.get("AI_RETRY_COUNT", "2")),
            retry_interval_ms=int(os.environ.get("AI_RETRY_INTERVAL_MS", "3000")),
        )
    )

    ai = AiClient(
        http,
        AiConfig(
            api_key=api_key,
            base_url=os.environ.get("AI_BASE_URL", "https://api.yuweixun.site/v1"),
            model=os.environ.get("AI_MODEL", "llama-3.3-70b-versatile"),
            temperature=float(os.environ.get("AI_TEMPERATURE", "0.5")),
            timeout_ms=int(os.environ.get("AI_TIMEOUT_MS", "60000")),
            retry_count=int(os.environ.get("AI_RETRY_COUNT", "2")),
            retry_interval_ms=int(os.environ.get("AI_RETRY_INTERVAL_MS", "3000")),
        ),
    )

    summary = ai.summarize(content)
    print("========================================")
    print("[ai_summary]")
    print(summary)
    print("========================================")
    return 0 if summary and summary != "AI 总结失败" else 2


if __name__ == "__main__":
    raise SystemExit(main())
