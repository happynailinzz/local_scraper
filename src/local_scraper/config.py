from __future__ import annotations

from dataclasses import dataclass
import os


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    list_url: str
    base_url: str
    user_agent: str

    db_path: str
    dedupe_strategy: str

    # Optional: force DB run_id (used by WebUI)
    run_id_override: str | None

    keyword_regex: str
    days_lookback: int
    loop_delay_seconds: float
    max_items_per_run: int

    http_timeout_ms: int
    http_retry_count: int
    http_retry_interval_ms: int

    ai_api_key: str
    ai_base_url: str
    ai_model: str
    ai_temperature: float
    ai_timeout_ms: int
    ai_retry_count: int
    ai_retry_interval_ms: int

    feishu_webhook_url: str | None

    # Optional: fetch zcpt pages via a relay service (for overseas deployments)
    zcpt_relay_base_url: str | None = None
    zcpt_relay_token: str | None = None

    feishu_notify_mode: str = "digest"
    feishu_card_image_url: str | None = None

    dry_run: bool = False
    ai_disabled: bool = False
    use_test_fixtures: bool = False

    log_json: bool = False
    log_level: str = "info"

    # Display / linking
    keywords_label: str | None = None
    webui_public_url: str | None = None

    # Adaptive throttling for large runs
    adaptive_delay_threshold_pages: int = 10
    batch_size: int = 50
    delay_increment_seconds: float = 1.0
    max_loop_delay_seconds: float = 10.0

    # Pagination limits
    max_pages_total: int = 200
    max_pages_per_category: int = 50

    @classmethod
    def from_env(cls) -> "Config":
        dry_run = _parse_bool(os.environ.get("DRY_RUN"), False)
        ai_disabled = _parse_bool(os.environ.get("AI_DISABLED"), False)
        ai_api_key = os.environ.get("AI_API_KEY", "").strip()
        if not ai_api_key and not (dry_run or ai_disabled):
            raise RuntimeError(
                "AI_API_KEY is required (unless DRY_RUN=true or AI_DISABLED=true)"
            )

        feishu_webhook = os.environ.get("FEISHU_WEBHOOK_URL")
        if feishu_webhook:
            feishu_webhook = feishu_webhook.strip() or None

        feishu_notify_mode = (
            (os.environ.get("FEISHU_NOTIFY_MODE") or "digest").strip().lower()
        )
        if feishu_notify_mode not in {"digest", "per_item"}:
            feishu_notify_mode = "digest"

        zcpt_relay_base_url = (
            os.environ.get("ZCPT_RELAY_BASE_URL") or ""
        ).strip() or None
        zcpt_relay_token = (os.environ.get("ZCPT_RELAY_TOKEN") or "").strip() or None

        return cls(
            list_url=os.environ.get(
                "LIST_URL", "https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html"
            ),
            base_url=os.environ.get("BASE_URL", "https://zcpt.zgpmsm.com.cn"),
            user_agent=os.environ.get(
                "USER_AGENT",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            ),
            db_path=os.environ.get("DB_PATH", "data/zhaocai.db"),
            dedupe_strategy=os.environ.get("DEDUPE_STRATEGY", "title"),
            run_id_override=(os.environ.get("RUN_ID_OVERRIDE") or "").strip() or None,
            keyword_regex=os.environ.get(
                "KEYWORD_REGEX", r"(系统|软件|平台|大数据|AI|采购|招标)"
            ),
            days_lookback=max(1, _parse_int(os.environ.get("DAYS_LOOKBACK"), 2)),
            loop_delay_seconds=float(os.environ.get("LOOP_DELAY", "1")),
            max_items_per_run=_parse_int(os.environ.get("MAX_ITEMS_PER_RUN"), 50),
            http_timeout_ms=_parse_int(os.environ.get("HTTP_TIMEOUT_MS"), 30000),
            http_retry_count=_parse_int(os.environ.get("HTTP_RETRY_COUNT"), 3),
            http_retry_interval_ms=_parse_int(
                os.environ.get("HTTP_RETRY_INTERVAL_MS"), 2000
            ),
            zcpt_relay_base_url=zcpt_relay_base_url,
            zcpt_relay_token=zcpt_relay_token,
            ai_api_key=ai_api_key,
            ai_base_url=os.environ.get("AI_BASE_URL", "https://api.yuweixun.site/v1"),
            ai_model=os.environ.get("AI_MODEL", "llama-3.3-70b-versatile"),
            ai_temperature=float(os.environ.get("AI_TEMPERATURE", "0.5")),
            ai_timeout_ms=_parse_int(os.environ.get("AI_TIMEOUT_MS"), 60000),
            ai_retry_count=_parse_int(os.environ.get("AI_RETRY_COUNT"), 2),
            ai_retry_interval_ms=_parse_int(
                os.environ.get("AI_RETRY_INTERVAL_MS"), 3000
            ),
            feishu_webhook_url=feishu_webhook,
            feishu_notify_mode=feishu_notify_mode,
            feishu_card_image_url=(
                os.environ.get("FEISHU_CARD_IMAGE_URL") or ""
            ).strip()
            or None,
            dry_run=dry_run,
            ai_disabled=ai_disabled,
            use_test_fixtures=_parse_bool(os.environ.get("USE_TEST_FIXTURES"), False),
            log_json=_parse_bool(os.environ.get("LOG_JSON"), False),
            log_level=os.environ.get("LOG_LEVEL", "info"),
            keywords_label=(os.environ.get("KEYWORDS_LABEL") or "").strip() or None,
            webui_public_url=(os.environ.get("WEBUI_PUBLIC_URL") or "").strip() or None,
            adaptive_delay_threshold_pages=max(
                0, _parse_int(os.environ.get("ADAPTIVE_DELAY_THRESHOLD_PAGES"), 10)
            ),
            batch_size=max(1, _parse_int(os.environ.get("BATCH_SIZE"), 50)),
            delay_increment_seconds=float(
                os.environ.get("DELAY_INCREMENT_SECONDS", "1")
            ),
            max_loop_delay_seconds=float(
                os.environ.get("MAX_LOOP_DELAY_SECONDS", "10")
            ),
            max_pages_total=max(1, _parse_int(os.environ.get("MAX_PAGES_TOTAL"), 200)),
            max_pages_per_category=max(
                1, _parse_int(os.environ.get("MAX_PAGES_PER_CATEGORY"), 50)
            ),
        )
