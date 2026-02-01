from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_scraper.ai_client import AiClient, AiConfig
from local_scraper.http_client import HttpClient, HttpConfig
from local_scraper.parser import extract_detail_content


@pytest.mark.integration
def test_ai_summary_live_api() -> None:
    api_key = (os.environ.get("AI_API_KEY") or "").strip()
    if not api_key:
        pytest.skip("AI_API_KEY not set")
    if (os.environ.get("AI_DISABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        pytest.skip("AI_DISABLED is enabled")

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "sample_detail.html"
    content = extract_detail_content(fixture_path.read_text(encoding="utf-8"))
    assert content

    http = HttpClient(
        HttpConfig(
            user_agent=os.environ.get("USER_AGENT", "pytest"),
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
    assert summary
    assert summary != "AI 总结失败"
