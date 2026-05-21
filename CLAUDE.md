# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`local_scraper` is a web scraping system for procurement announcements (招采信息) from Chinese government procurement websites. It collects, filters, deduplicates, AI-summarizes, and pushes notifications to Feishu (飞书). The system includes a WebUI with task scheduling capabilities.

**Primary target site**: `https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html`

The scraper also supports loading multiple site entry URLs from a Markdown file via `SITE_LIST_MARKDOWN_PATH`.

## Development Setup

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env to set AI_API_KEY, FEISHU_WEBHOOK_URL, WEBUI_USERNAME, WEBUI_PASSWORD

# Optional: crawl multiple sites from a Markdown file
# SITE_LIST_MARKDOWN_PATH=/Users/name/Downloads/抓取网页-官网精简版.md
```

## Common Commands

```bash
# Unit tests
pytest -q

# Single test file
pytest tests/test_workflow.py -q

# AI integration tests (requires AI_API_KEY and AI_DISABLED=false)
set -a; source .env; set +a
AI_DISABLED=false pytest -q -m integration

# One-time scraping run
AI_DISABLED=false python scripts/run.py --days-lookback 7 --keywords "采购" --max-items 10 --loop-delay 1 --log-level info

# One-time scraping run using a Markdown site list
AI_DISABLED=false python scripts/run.py --site-list-markdown "/Users/name/Downloads/抓取网页-官网精简版.md" --days-lookback 7 --keywords "采购" --max-items 20 --loop-delay 1 --log-level info

# Start WebUI (task scheduler runs in-process)
python scripts/webui.py
# Access at http://127.0.0.1:8000

# Backfill KEYWORDS_LABEL on existing tasks
python scripts/migrate_keywords_label.py --db-path data/zhaocai.db
```

## Architecture

### Core Data Flow (`src/local_scraper/workflow.py:run_once()`)

```
List collection → Date filter → Keyword filter → Dedup check (DB) → Detail fetch → AI summarize → DB persist → Feishu notify
```

1. **List collection**: By default the workflow crawls `LIST_URL`. If `SITE_LIST_MARKDOWN_PATH` is set, it first loads multiple site entry URLs from the Markdown file, then crawls each site in sequence. Existing parsers (`parse_list_page()`, `parse_notice_list_page()`, `parse_zcpt_list_page()`) run first on every page; if none match, a generic dated-link parser is used as a fallback. ZCPT pagination uses `?pageIndex=N` (handled by `_zcpt_next_page_url()`). Stops when dates fall outside the lookback window.

2. **Filtering**: Date normalization via `normalize_date()` (handles multiple formats), then `KEYWORD_REGEX` match on title. All timestamps use Shanghai timezone (`time_utils.shanghai_recent_days()`).

3. **Deduplication**: `db.is_duplicate()` checks before inserting; race condition handled by `insert_announcement_base()` returning `False` on conflict.

4. **AI Summary**: `AiClient.summarize()` → fallback to `build_fallback_summary()` if AI fails or is disabled.

5. **Feishu Notifications**: Two modes controlled by `FEISHU_NOTIFY_MODE`:
   - `digest`: Batched into cards of 10 items each, sent after run completes
   - `per_item`: Card sent per new item, then a summary card

6. **Adaptive Throttling**: Activates when `page_turns > ADAPTIVE_DELAY_THRESHOLD_PAGES`. Increases delay by `DELAY_INCREMENT_SECONDS` every `BATCH_SIZE` items up to `MAX_LOOP_DELAY_SECONDS`.

### Key Components

| File | Purpose |
|------|---------|
| `config.py` | `Config.from_env()` — all config from environment variables |
| `db.py` | SQLite: `announcements`, `runs`, `tasks` tables |
| `http_client.py` | Retry logic + optional ZCPT relay (`relay_zcpt_base_url`) |
| `ai_client.py` | OpenAI-compatible API calls |
| `feishu_client.py` | Card builders (`build_digest_card`, `build_new_item_card`, etc.) |
| `parser.py` | HTML parsing for list pages and detail content |
| `web/app.py` | FastAPI app with Basic Auth, settings UI, SSE log streaming |
| `web/task_scheduler.py` | APScheduler-based cron/interval task management |

### WebUI (`web/app.py`)

- **Auth**: HTTP Basic Auth via `WEBUI_USERNAME`/`WEBUI_PASSWORD` (checked on every request)
- **Settings page**: Reads/writes `.env` file via `python-dotenv`; model presets defined in `_MODEL_PRESETS`
- **Live logs**: SSE (`/runs/{id}/stream`) streams from an in-memory `RunManager` that stores `LiveRun` objects per run
- **Task scheduler**: `TaskScheduler` instance initialized at startup; task definitions stored in `tasks` DB table

### ZCPT Relay (Overseas Access)

For overseas servers that cannot access `zcpt.zgpmsm.com.cn`:

- **Relay Server** (China): Set `RELAY_ENABLED=true`, `RELAY_TOKEN=<secret>`
- **Client** (Overseas): Set `ZCPT_RELAY_BASE_URL=<relay-url>`, `ZCPT_RELAY_TOKEN=<secret>`
- Relay only proxies to `zcpt.zgpmsm.com.cn` — not a generic proxy

## Configuration Reference

All config flows through `Config.from_env()` in `config.py`. Key variables:

| Variable | Default | Notes |
|----------|---------|-------|
| `AI_API_KEY` | — | Required unless `DRY_RUN=true` or `AI_DISABLED=true` |
| `AI_BASE_URL` | `https://api.yuweixun.site/v1` | OpenAI-compatible endpoint |
| `AI_MODEL` | `llama-3.3-70b-versatile` | |
| `DAYS_LOOKBACK` | `2` | Min 1 |
| `KEYWORD_REGEX` | `(系统\|软件\|平台\|大数据\|AI\|采购\|招标)` | Python regex |
| `SITE_LIST_MARKDOWN_PATH` | — | Optional markdown file containing multiple site entry links |
| `DEDUPE_STRATEGY` | `title` | `title`, `url`, or `title_date` |
| `MAX_ITEMS_PER_RUN` | `50` | `0` = unlimited |
| `MAX_PAGES_TOTAL` | `200` | Global page cap |
| `MAX_PAGES_PER_CATEGORY` | `50` | Per-category cap |
| `FEISHU_NOTIFY_MODE` | `digest` | `digest` or `per_item` |
| `WEBUI_PUBLIC_URL` | — | Used in digest card "view all" link |

## Testing Patterns

- **Fixtures**: HTML fixtures in `tests/fixtures/`. Set `USE_TEST_FIXTURES=true` to bypass live HTTP.
- **Integration tests**: Marked `@pytest.mark.integration`; require real `AI_API_KEY`.
- **Relay tests**: `tests/test_http_relay.py` validates relay functionality without live ZCPT access.

## Database Schema

SQLite at `data/zhaocai.db`:
- `announcements`: `title`, `url`, `date`, `content`, `ai_summary`, `status` (`NEW`/`PROCESSED`/`FAILED`)
- `runs`: Execution history with `total_processed`, `total_new`, `total_duplicate`, `error`
- `tasks`: Scheduled task config with cron/interval fields

## Deployment

```bash
# Docker (recommended for server)
docker-compose up -d

# Release: push tag to trigger GitHub Actions → GHCR image build
git tag v0.x.x && git push origin v0.x.x
```

GHCR image: `ghcr.io/<owner>/local-scraper:latest`
Persist `data/` and `logs/` volumes for SQLite and log files.
