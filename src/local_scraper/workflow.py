from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
import time
import traceback
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .ai_client import AiClient, AiConfig
from .config import Config
from .db import Database
from .fallback_summary import build_fallback_summary
from .feishu_client import (
    FeishuClient,
    FeishuConfig,
    build_error_card,
    build_digest_card,
    build_new_item_card,
    build_summary_card,
)
from .http_client import HttpClient, HttpConfig
from .logger import Logger
from .parser import (
    extract_detail_content,
    parse_category_links,
    parse_list_page,
    parse_next_page_url,
    parse_notice_list_page,
    parse_zcpt_list_page,
)
from .time_utils import normalize_date, shanghai_recent_days


@dataclass(frozen=True)
class ListCollectionResult:
    items: list[tuple[str, str, str]]
    pages_seen: int
    page_turns: int


def _read_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fixtures_dir() -> Path:
    # Prefer local_scraper-owned fixtures for portability.
    here = Path(__file__).resolve()
    project_dir = here.parents[2]
    local = project_dir / "tests" / "fixtures"
    if local.exists():
        return local

    # Fallback to repo-level fixtures (older layout).
    repo_root = here.parents[3]
    return repo_root / "n8n 工作流" / "tests"


def _collect_list_items(
    cfg: Config, http: HttpClient, log: Logger, earliest_keep: date
) -> ListCollectionResult:
    """Return list items as (title, link, date_raw) from start page and discovered category pages."""

    if cfg.use_test_fixtures:
        list_html = _read_fixture(_fixtures_dir() / "sample_list.html")
        items = parse_list_page(list_html)
        log.info("list.fixtures", items=len(items))
        return ListCollectionResult(
            items=[(it.title, it.link, it.date_raw) for it in items],
            pages_seen=1,
            page_turns=0,
        )

    start_html = http.get_text(cfg.list_url)
    log.info("list.fetch", url=cfg.list_url)

    raw: list[tuple[str, str, str]] = []
    for it in parse_list_page(start_html):
        raw.append((it.title, it.link, it.date_raw))
    for it in parse_notice_list_page(start_html):
        raw.append((it.title, it.link, it.date_raw))
    for it in parse_zcpt_list_page(start_html):
        raw.append((it.title, it.link, it.date_raw))

    seen_pages: set[str] = {cfg.list_url}
    queue = parse_category_links(start_html, base_url=cfg.base_url)
    log.debug("list.discover_categories", count=len(queue))

    # Explore category pages (site nav tree). For each category page, follow pagination
    # until records are older than our lookback window.
    max_pages_total = max(1, cfg.max_pages_total)
    max_pages_per_category = max(1, cfg.max_pages_per_category)
    page_turns = 0
    while queue and len(seen_pages) < max_pages_total:
        url = queue.pop(0)
        if url in seen_pages:
            continue
        seen_pages.add(url)
        # Walk pages within this category.
        page_url = url
        for page_idx in range(1, max_pages_per_category + 1):
            try:
                html = http.get_text(page_url)
            except Exception:  # noqa: BLE001
                log.warn("category.fetch_failed", url=page_url)
                break

            log.debug("category.fetch", url=page_url, page=page_idx)

            for it in parse_list_page(html):
                raw.append((it.title, it.link, it.date_raw))

            notices = parse_notice_list_page(html)
            zcpt_items = parse_zcpt_list_page(html)
            for it in notices:
                raw.append((it.title, it.link, it.date_raw))
            for it in zcpt_items:
                raw.append((it.title, it.link, it.date_raw))

            # Determine whether to stop paging based on lookback.
            # - legacy pages: assume sorted desc, stop when min_date < earliest_keep
            # - zcpt pages: dates can be mixed, stop only when ALL dates are older
            if zcpt_items:
                should_stop, max_date = _zcpt_should_stop_page(
                    zcpt_items, earliest_keep
                )
                if should_stop:
                    log.debug(
                        "category.stop_old",
                        url=page_url,
                        max_date=max_date,
                        earliest_keep=earliest_keep.isoformat(),
                    )
                    break
            elif notices:
                try:
                    min_d = min(date.fromisoformat(n.date_raw) for n in notices)
                    if min_d < earliest_keep:
                        log.debug(
                            "category.stop_old",
                            url=page_url,
                            min_date=min_d.isoformat(),
                            earliest_keep=earliest_keep.isoformat(),
                        )
                        break
                except Exception:
                    pass

            next_url = parse_next_page_url(html, current_url=page_url)
            if not next_url:
                next_url = _zcpt_next_page_url(html, page_url)

            if not next_url or next_url in seen_pages:
                break
            log.debug("category.next_page", from_url=page_url, to_url=next_url)
            seen_pages.add(next_url)
            page_url = next_url
            page_turns += 1

        # keep discovering deeper levels (only from the category root page)
        try:
            root_html = http.get_text(url)
            for u in parse_category_links(root_html, base_url=cfg.base_url):
                if u not in seen_pages:
                    queue.append(u)
        except Exception:
            pass

    # De-dupe raw list by (title, link, date_raw)
    out: list[tuple[str, str, str]] = []
    seen_items: set[tuple[str, str, str]] = set()
    for t, l, d in raw:
        key = (t, l, d)
        if key in seen_items:
            continue
        seen_items.add(key)
        out.append(key)

    log.info(
        "list.collected",
        site=("zcpt" if "zcpt.zgpmsm.com.cn" in cfg.list_url else "unknown"),
        items=len(out),
        pages=len(seen_pages),
        page_turns=page_turns,
        raw_items=len(raw),
    )
    return ListCollectionResult(
        items=out, pages_seen=len(seen_pages), page_turns=page_turns
    )


_RE_ZCPT_TOTAL = re.compile(r"var\s+total\s*=\s*(\d+)")
_RE_ZCPT_PAGE_SIZE = re.compile(r"pageSize\s*:\s*(\d+)")


def _zcpt_should_stop_page(
    zcpt_items: list, earliest_keep: date
) -> tuple[bool, str | None]:
    """Stop only when ALL dates on page are older than earliest_keep."""

    dates: list[date] = []
    for it in zcpt_items:
        try:
            dates.append(date.fromisoformat(getattr(it, "date_raw")))
        except Exception:
            continue
    if not dates:
        return False, None
    max_d = max(dates)
    return (max_d < earliest_keep), max_d.isoformat()


def _set_query_param(url: str, key: str, value: str) -> str:
    parts = urlsplit(url)
    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    qs[key] = value
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(qs), parts.fragment)
    )


def _zcpt_next_page_url(html: str, current_url: str) -> str | None:
    """zcpt list pagination uses ?pageIndex=N."""

    m_total = _RE_ZCPT_TOTAL.search(html)
    m_size = _RE_ZCPT_PAGE_SIZE.search(html)
    if not m_total or not m_size:
        return None
    try:
        total = int(m_total.group(1))
        page_size = int(m_size.group(1))
    except Exception:
        return None
    if total <= 0 or page_size <= 0:
        return None

    parts = urlsplit(current_url)
    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    try:
        current = int(qs.get("pageIndex", "1"))
    except Exception:
        current = 1

    max_pages = (total + page_size - 1) // page_size
    if current >= max_pages:
        return None
    return _set_query_param(current_url, "pageIndex", str(current + 1))


def run_once(cfg: Config) -> dict[str, object]:
    start = time.time()
    recent = shanghai_recent_days()

    log = Logger(enabled=True, json_mode=cfg.log_json, level=cfg.log_level)
    log.info(
        "run.start",
        list_url=cfg.list_url,
        db_path=cfg.db_path,
        days_lookback=cfg.days_lookback,
        max_items=cfg.max_items_per_run,
        dry_run=cfg.dry_run,
        ai_disabled=cfg.ai_disabled,
        feishu_enabled=bool(cfg.feishu_webhook_url),
        dedupe_strategy=cfg.dedupe_strategy,
        max_pages_total=cfg.max_pages_total,
        max_pages_per_category=cfg.max_pages_per_category,
    )

    http = HttpClient(
        HttpConfig(
            user_agent=cfg.user_agent,
            timeout_ms=cfg.http_timeout_ms,
            retry_count=cfg.http_retry_count,
            retry_interval_ms=cfg.http_retry_interval_ms,
            relay_zcpt_base_url=cfg.zcpt_relay_base_url,
            relay_zcpt_token=cfg.zcpt_relay_token,
        )
    )

    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    db.init_schema()
    run = db.start_run(run_id_override=cfg.run_id_override)

    feishu: FeishuClient | None = None
    if cfg.feishu_webhook_url:
        feishu = FeishuClient(
            http,
            FeishuConfig(
                webhook_url=cfg.feishu_webhook_url,
                timeout_ms=cfg.http_timeout_ms,
                retry_count=2,
                retry_interval_ms=1000,
            ),
        )

    ai: AiClient | None = None
    if not (cfg.dry_run or cfg.ai_disabled):
        ai = AiClient(
            http,
            AiConfig(
                api_key=cfg.ai_api_key,
                base_url=cfg.ai_base_url,
                model=cfg.ai_model,
                temperature=cfg.ai_temperature,
                timeout_ms=cfg.ai_timeout_ms,
                retry_count=cfg.ai_retry_count,
                retry_interval_ms=cfg.ai_retry_interval_ms,
            ),
        )

    total_processed = 0
    total_new = 0
    total_duplicate = 0

    item_errors: list[str] = []
    new_items: list[dict[str, str]] = []

    error_text: str | None = None
    status = "COMPLETED"

    try:
        earliest_keep = date.fromisoformat(recent.today) - timedelta(
            days=max(cfg.days_lookback - 1, 0)
        )
        collected = _collect_list_items(cfg, http, log, earliest_keep=earliest_keep)
        raw_items = collected.items
        if not raw_items:
            log.warn("run.no_items")
            duration = int(round(time.time() - start))
            finished_at = shanghai_recent_days().now_iso
            db.finish_run(
                run_id=run.run_id,
                status=status,
                finished_at=finished_at,
                duration_seconds=duration,
                total_processed=0,
                total_new=0,
                total_duplicate=0,
                error=None,
            )
            db.close()
            return {
                "status": status,
                "run_id": run.run_id,
                "execution_time": run.started_at,
                "duration_seconds": duration,
                "total_processed": 0,
                "total_new": 0,
                "total_duplicate": 0,
            }

        keyword_re = re.compile(cfg.keyword_regex)
        now_dt = datetime.fromisoformat(recent.now_iso)

        normalized: list[tuple[str, str, str]] = []
        for title, link, date_raw in raw_items:
            d = normalize_date(date_raw, now=now_dt)
            if not d:
                continue
            normalized.append((title, link, d))

        if cfg.use_test_fixtures and normalized:
            base_d = max(d for _, _, d in normalized)
            base_date = date.fromisoformat(base_d)
        else:
            base_date = date.fromisoformat(recent.today)

        lookback = cfg.days_lookback
        if lookback < 1:
            lookback = 1

        allowed_dates = {
            (base_date - timedelta(days=i)).isoformat() for i in range(lookback)
        }

        log.debug(
            "filter.allowed_dates",
            count=len(allowed_dates),
            first=min(allowed_dates),
            last=max(allowed_dates),
        )

        filtered: list[tuple[str, str, str]] = []
        for title, link, d in normalized:
            if d not in allowed_dates:
                continue
            if not keyword_re.search(title):
                continue
            filtered.append((title, link, d))

        log.info("filter.result", normalized=len(normalized), matched=len(filtered))

        adaptive = collected.page_turns > cfg.adaptive_delay_threshold_pages
        current_delay = max(cfg.loop_delay_seconds, 0.0)
        if adaptive:
            log.info(
                "throttle.enabled",
                page_turns=collected.page_turns,
                threshold=cfg.adaptive_delay_threshold_pages,
                batch_size=cfg.batch_size,
                delay_increment_seconds=cfg.delay_increment_seconds,
                max_loop_delay_seconds=cfg.max_loop_delay_seconds,
            )

        max_items = cfg.max_items_per_run
        if max_items < 0:
            max_items = 0

        log.info(
            "run.plan",
            total_candidates=len(raw_items),
            total_normalized=len(normalized),
            total_matched=len(filtered),
            max_items=max_items,
        )

        for idx, (title, link, d) in enumerate(filtered):
            if max_items and idx >= max_items:
                break
            if idx > 0 and current_delay > 0:
                time.sleep(current_delay)

            abs_url = (
                link
                if link.startswith("http")
                else urljoin(cfg.base_url.rstrip("/") + "/", link)
            )
            exists = db.is_duplicate(title=title, url=abs_url, date=d)

            if exists:
                total_duplicate += 1
                total_processed += 1
                log.debug("item.duplicate", title=title, date=d)
                continue

            total_new += 1
            total_processed += 1

            log.info("item.new", title=title, date=d)

            if cfg.dry_run:
                log.info("item.skip_dry_run", title=title)
                continue

            inserted = db.insert_announcement_base(
                title=title, url=abs_url, date=d, status="NEW"
            )
            if not inserted:
                total_duplicate += 1
                total_new -= 1
                log.info("item.race_duplicate", title=title)
                continue

            try:
                detail_html: str
                if cfg.use_test_fixtures:
                    detail_html = _read_fixture(_fixtures_dir() / "sample_detail.html")
                else:
                    detail_html = http.get_text(abs_url)

                log.debug("detail.fetched", title=title, url=abs_url)

                content = extract_detail_content(detail_html)
                log.debug("detail.extracted", title=title, content_len=len(content))
                if not content:
                    ai_summary = "AI 总结失败"
                elif ai is None:
                    ai_summary = build_fallback_summary(title=title, content=content)
                else:
                    ai_summary = ai.summarize(content)
                    if not ai_summary or ai_summary == "AI 总结失败":
                        ai_summary = build_fallback_summary(
                            title=title, content=content
                        )

                log.debug("item.summarized", title=title, summary_len=len(ai_summary))

                db.update_announcement_detail(
                    title=title,
                    content=content,
                    ai_summary=ai_summary,
                    status="PROCESSED",
                )

                if feishu:
                    try:
                        if cfg.feishu_notify_mode == "per_item":
                            card = build_new_item_card(
                                title=title, date=d, ai_summary=ai_summary, url=abs_url
                            )
                            feishu.send_card(card)
                            log.info("feishu.sent_item", title=title)
                        else:
                            new_items.append(
                                {
                                    "title": title,
                                    "date": d,
                                    "ai_summary": ai_summary,
                                    "url": abs_url,
                                }
                            )
                    except Exception:  # noqa: BLE001
                        item_errors.append(f"feishu_send_failed: {title}")
                        log.warn("feishu.send_item_failed", title=title)

            except Exception as e:  # noqa: BLE001
                item_errors.append(f"item_failed: {title}: {e}")
                log.warn("item.failed", title=title, error=str(e))
                db.update_announcement_detail(
                    title=title,
                    content="",
                    ai_summary="AI 总结失败",
                    status="FAILED",
                )
                continue

            # Adaptive throttling: increase delay after each batch.
            if (
                adaptive
                and cfg.batch_size > 0
                and total_processed % cfg.batch_size == 0
            ):
                current_delay = min(
                    cfg.max_loop_delay_seconds,
                    current_delay + max(cfg.delay_increment_seconds, 0.0),
                )
                log.info(
                    "throttle.step", processed=total_processed, loop_delay=current_delay
                )

        duration = int(round(time.time() - start))
        finished_at = shanghai_recent_days().now_iso

        db.finish_run(
            run_id=run.run_id,
            status=status,
            finished_at=finished_at,
            duration_seconds=duration,
            total_processed=total_processed,
            total_new=total_new,
            total_duplicate=total_duplicate,
            error="\n".join(item_errors)[:4000] if item_errors else None,
        )

        if feishu and total_new > 0:
            try:
                if cfg.feishu_notify_mode == "digest":
                    chunk_size = 10
                    total_items = len(new_items)
                    for i in range(0, len(new_items), chunk_size):
                        range_start = i + 1
                        range_end = min(i + chunk_size, total_items)
                        feishu.send_card(
                            build_digest_card(
                                keyword_label=cfg.keywords_label or cfg.keyword_regex,
                                execution_time=run.started_at,
                                duration_seconds=duration,
                                total_new=total_new,
                                total_duplicate=total_duplicate,
                                total_processed=total_processed,
                                items=new_items[i : i + chunk_size],
                                webui_public_url=cfg.webui_public_url,
                                days_lookback=cfg.days_lookback,
                                image_url=cfg.feishu_card_image_url,
                                range_start=range_start,
                                range_end=range_end,
                                total_items=total_items,
                            )
                        )
                else:
                    feishu.send_card(
                        build_summary_card(
                            execution_time=run.started_at,
                            duration_seconds=duration,
                            total_processed=total_processed,
                            total_new=total_new,
                            total_duplicate=total_duplicate,
                        )
                    )
            except Exception:  # noqa: BLE001
                pass

        log.info(
            "run.completed",
            duration_seconds=duration,
            total_processed=total_processed,
            total_new=total_new,
            total_duplicate=total_duplicate,
            item_errors=len(item_errors),
        )

        db.close()
        return {
            "status": status,
            "run_id": run.run_id,
            "execution_time": run.started_at,
            "duration_seconds": duration,
            "total_processed": total_processed,
            "total_new": total_new,
            "total_duplicate": total_duplicate,
        }

    except Exception as e:  # noqa: BLE001
        status = "FAILED"
        duration = int(round(time.time() - start))
        finished_at = shanghai_recent_days().now_iso
        tb = traceback.format_exc(limit=5)
        error_text = f"{e}\n{tb}"

        log.error("run.failed", error=str(e))

        db.finish_run(
            run_id=run.run_id,
            status=status,
            finished_at=finished_at,
            duration_seconds=duration,
            total_processed=total_processed,
            total_new=total_new,
            total_duplicate=total_duplicate,
            error=error_text[:4000],
        )

        if feishu:
            feishu.send_card(build_error_card(timestamp=finished_at, message=str(e)))

        db.close()
        return {
            "status": status,
            "run_id": run.run_id,
            "execution_time": run.started_at,
            "duration_seconds": duration,
            "total_processed": total_processed,
            "total_new": total_new,
            "total_duplicate": total_duplicate,
            "error": error_text,
        }
