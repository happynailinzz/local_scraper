from __future__ import annotations

import base64
import json
import os
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.responses import Response, StreamingResponse

import requests
from dotenv import dotenv_values, set_key

from ..config import Config
from ..db import Database
from ..parser import parse_site_list_markdown
from .task_scheduler import TaskScheduler


_BASE_DIR = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_BASE_DIR / "templates"))
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"
_MODEL_PRESETS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "custom",
]


def _normalize_base_url(list_url: str, fallback: str) -> str:
    parsed = urlsplit(list_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return fallback


def _load_env_config() -> dict[str, str]:
    if not _ENV_FILE.exists():
        return {}
    values = dotenv_values(str(_ENV_FILE))
    out: dict[str, str] = {}
    for k, v in values.items():
        if k is None:
            continue
        out[str(k)] = "" if v is None else str(v)
    return out


def _save_env_config(values: dict[str, str]) -> None:
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _ENV_FILE.exists():
        _ENV_FILE.touch()
    for key, value in values.items():
        set_key(str(_ENV_FILE), key, value)
        os.environ[key] = value


def _basic_auth(request: Request) -> None:
    user = os.environ.get("WEBUI_USERNAME", "").strip()
    pwd = os.environ.get("WEBUI_PASSWORD", "").strip()
    if not user or not pwd:
        raise HTTPException(
            status_code=500, detail="WEBUI_USERNAME/WEBUI_PASSWORD not set"
        )

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Basic "):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})

    try:
        raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        username, password = raw.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})

    if not (
        secrets.compare_digest(username, user) and secrets.compare_digest(password, pwd)
    ):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})


@dataclass
class LiveRun:
    run_id: str
    started_at: float
    status: str
    lines: list[str]
    done: bool
    log_file: str


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, LiveRun] = {}

    def get(self, run_id: str) -> LiveRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def start(self, cfg_overrides: dict[str, str]) -> str:
        import uuid
        import subprocess

        # Use the same run_id as DB (RUN_ID_OVERRIDE) to make /runs/{run_id} consistent.
        run_id = str(uuid.uuid4())
        log_file = str(self._log_path(run_id))
        live = LiveRun(
            run_id=run_id,
            started_at=time.time(),
            status="RUNNING",
            lines=[],
            done=False,
            log_file=log_file,
        )
        with self._lock:
            self._runs[run_id] = live

        def worker() -> None:
            env = os.environ.copy()
            env.update(cfg_overrides)
            env["RUN_ID_OVERRIDE"] = run_id
            env["LOG_JSON"] = "true"
            env["LOG_LEVEL"] = env.get("LOG_LEVEL", "info")

            cmd = [sys.executable, "scripts/run.py", "--log-json"]
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(Path(__file__).resolve().parents[3]),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
            except Exception as e:
                self._append(run_id, f"[webui] failed to start run: {e}")
                self._finish(run_id, status="FAILED")
                return

            assert proc.stdout is not None
            for line in proc.stdout:
                self._append(run_id, line.rstrip("\n"))
            code = proc.wait()
            self._finish(run_id, status="COMPLETED" if code == 0 else "FAILED")

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return run_id

    def _append(self, run_id: str, line: str) -> None:
        with self._lock:
            r = self._runs.get(run_id)
            if not r:
                return
            r.lines.append(line)
            if len(r.lines) > 2000:
                r.lines = r.lines[-2000:]
            log_file = r.log_file

        # Persist logs so they can be viewed after WebUI restarts.
        try:
            p = Path(log_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _finish(self, run_id: str, status: str) -> None:
        with self._lock:
            r = self._runs.get(run_id)
            if not r:
                return
            r.status = status
            r.done = True

    def _log_path(self, run_id: str) -> Path:
        project_root = Path(__file__).resolve().parents[3]
        return project_root / "logs" / "webui_runs" / f"{run_id}.log"

    def get_log_file(self, run_id: str) -> str | None:
        with self._lock:
            r = self._runs.get(run_id)
            if r:
                return r.log_file

        p = self._log_path(run_id)
        return str(p) if p.exists() else None


_RUNS = RunManager()
_TASKS = TaskScheduler()


app = FastAPI(title="local_scraper web")


def _relay_enabled() -> bool:
    return (os.environ.get("RELAY_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "t",
        "yes",
        "y",
        "on",
    }


def _relay_auth(request: Request) -> None:
    token = (os.environ.get("RELAY_TOKEN") or "").strip()
    if not token:
        raise HTTPException(status_code=500, detail="RELAY_TOKEN not set")

    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = auth.split(" ", 1)[1].strip()
    if not secrets.compare_digest(presented, token):
        raise HTTPException(status_code=403)


class _RelayZcptFetchIn(BaseModel):
    path: str
    query: str | None = ""


@app.post("/relay/zcpt/fetch")
def relay_zcpt_fetch(payload: _RelayZcptFetchIn, request: Request) -> Response:
    """Fetch zcpt pages from a China-based host.

    This endpoint is intentionally NOT a general-purpose proxy.
    - Only targets https://zcpt.zgpmsm.com.cn
    - Requires RELAY_ENABLED=true and a Bearer token
    """

    if not _relay_enabled():
        raise HTTPException(status_code=404)

    _relay_auth(request)

    path = (payload.path or "").strip() or "/"
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise HTTPException(status_code=400, detail="invalid path")

    sp = urlsplit(path)
    if sp.scheme or sp.netloc:
        raise HTTPException(status_code=400, detail="invalid path")

    q = (payload.query or "").lstrip("?")
    target_parts = ("https", "zcpt.zgpmsm.com.cn", sp.path, q, "")
    target_url = urlunsplit(target_parts)

    timeout_ms = int((os.environ.get("RELAY_TIMEOUT_MS") or "30000").strip() or 30000)
    ua = (
        (os.environ.get("RELAY_USER_AGENT") or "").strip()
        or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        resp = requests.get(
            target_url,
            headers={"User-Agent": ua},
            timeout=timeout_ms / 1000,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e))

    content_type = resp.headers.get("Content-Type") or "application/octet-stream"
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={"Content-Type": content_type},
    )


@app.get("/", response_class=HTMLResponse)
def home(_: Any = Depends(_basic_auth)) -> RedirectResponse:
    return RedirectResponse("/announcements", status_code=302)


@app.get("/settings/init", response_class=HTMLResponse)
def init_settings(
    request: Request,
    saved: int = 0,
    _: Any = Depends(_basic_auth),
) -> HTMLResponse:
    cfg: Config | None = None
    try:
        cfg = Config.from_env()
    except Exception:
        cfg = None
    env_cfg = _load_env_config()

    list_url = env_cfg.get("LIST_URL") or (
        cfg.list_url if cfg else "https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html"
    )
    base_url = env_cfg.get("BASE_URL") or (
        cfg.base_url if cfg else "https://zcpt.zgpmsm.com.cn"
    )
    feishu_webhook_url = env_cfg.get("FEISHU_WEBHOOK_URL")
    if feishu_webhook_url is None:
        feishu_webhook_url = (cfg.feishu_webhook_url or "") if cfg else ""
    ai_base_url = env_cfg.get("AI_BASE_URL") or (
        cfg.ai_base_url if cfg else "https://api.yuweixun.site/v1"
    )
    ai_model = env_cfg.get("AI_MODEL") or (
        cfg.ai_model if cfg else "llama-3.1-8b-instant"
    )
    ai_api_key = env_cfg.get("AI_API_KEY") or (cfg.ai_api_key if cfg else "")
    ai_disabled = (
        (env_cfg.get("AI_DISABLED") or (str(cfg.ai_disabled) if cfg else "false"))
        .strip()
        .lower()
    )

    preset = ai_model if ai_model in _MODEL_PRESETS else "custom"
    custom_model = "" if preset != "custom" else ai_model

    return _TEMPLATES.TemplateResponse(
        request=request,
        name="init_settings.html",
        context={
            "request": request,
            "saved": saved == 1,
            "list_url": list_url,
            "base_url": base_url,
            "feishu_webhook_url": feishu_webhook_url,
            "feishu_notify_mode": cfg.feishu_notify_mode if cfg else "digest",
            "ai_base_url": ai_base_url,
            "ai_model": ai_model,
            "ai_model_preset": preset,
            "ai_model_custom": custom_model,
            "ai_api_key": ai_api_key,
            "ai_disabled": "true"
            if ai_disabled in {"1", "true", "yes", "on"}
            else "false",
            "model_presets": _MODEL_PRESETS,
        },
    )


@app.post("/settings/init")
def init_settings_save(
    list_url: str = Form(...),
    base_url: str = Form(""),
    feishu_webhook_url: str = Form(""),
    feishu_notify_mode: str = Form("digest"),
    ai_base_url: str = Form("https://api.yuweixun.site/v1"),
    ai_model_preset: str = Form("llama-3.1-8b-instant"),
    ai_model_custom: str = Form(""),
    ai_api_key: str = Form(""),
    ai_disabled: str = Form("false"),
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    list_url = list_url.strip()
    if not list_url:
        raise HTTPException(status_code=400, detail="LIST_URL 不能为空")

    if ai_model_preset == "custom":
        ai_model = ai_model_custom.strip()
    else:
        ai_model = ai_model_preset.strip()
    if not ai_model:
        raise HTTPException(status_code=400, detail="AI_MODEL 不能为空")

    notify_mode = feishu_notify_mode.strip().lower()
    if notify_mode not in {"digest", "per_item"}:
        notify_mode = "digest"

    disabled = ai_disabled.strip().lower() in {"1", "true", "yes", "on"}

    base_url = base_url.strip() or _normalize_base_url(
        list_url, "https://zcpt.zgpmsm.com.cn"
    )
    ai_base_url = ai_base_url.strip() or "https://api.yuweixun.site/v1"

    values = {
        "LIST_URL": list_url,
        "BASE_URL": base_url,
        "FEISHU_WEBHOOK_URL": feishu_webhook_url.strip(),
        "FEISHU_NOTIFY_MODE": notify_mode,
        "AI_BASE_URL": ai_base_url,
        "AI_MODEL": ai_model,
        "AI_API_KEY": ai_api_key.strip(),
        "AI_DISABLED": "true" if disabled else "false",
    }

    if not disabled and not values["AI_API_KEY"]:
        raise HTTPException(
            status_code=400, detail="AI_API_KEY 不能为空（除非 AI_DISABLED=true）"
        )

    _save_env_config(values)
    return RedirectResponse("/settings/init?saved=1", status_code=303)


@app.on_event("startup")
def _init_schema() -> None:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    db.init_schema()
    db.close()
    _TASKS.start()
    _TASKS.sync_from_db()


@app.on_event("shutdown")
def _shutdown_scheduler() -> None:
    _TASKS.shutdown()


@app.get("/announcements", response_class=HTMLResponse)
def announcements(
    request: Request,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    ai_summary_state: str | None = None,
    page: int = 1,
    page_size: int = 50,
    _: Any = Depends(_basic_auth),
) -> HTMLResponse:
    cfg = Config.from_env()
    page = max(1, page)
    page_size = min(200, max(10, page_size))
    offset = (page - 1) * page_size

    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    total, rows = db.list_announcements(
        q=q,
        date_from=date_from,
        date_to=date_to,
        status=status,
        ai_summary_state=ai_summary_state,
        limit=page_size,
        offset=offset,
    )
    db.close()

    return _TEMPLATES.TemplateResponse(
        request=request,
        name="announcements.html",
        context={
            "request": request,
            "rows": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "q": q or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "status": status or "",
            "ai_summary_state": (ai_summary_state or ""),
        },
    )


@app.get("/announcements/{announcement_id}", response_class=HTMLResponse)
def announcement_detail(
    request: Request,
    announcement_id: int,
    _: Any = Depends(_basic_auth),
) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    row = db.get_announcement(announcement_id)
    db.close()
    if not row:
        raise HTTPException(status_code=404)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="announcement_detail.html",
        context={"request": request, "row": row},
    )


@app.get("/runs", response_class=HTMLResponse)
def runs(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    _: Any = Depends(_basic_auth),
) -> HTMLResponse:
    cfg = Config.from_env()
    page = max(1, page)
    page_size = min(200, max(10, page_size))
    offset = (page - 1) * page_size

    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    total, rows = db.list_runs(limit=page_size, offset=offset)
    scrape_targets = db.list_scrape_targets()
    db.close()
    builtin_names = {row["name"] for row in _load_builtin_verified_sites()}
    builtin_selected_ids = {
        str(t["target_id"])
        for t in scrape_targets
        if str(t["name"]) in builtin_names and bool(t.get("enabled"))
    }

    return _TEMPLATES.TemplateResponse(
        request=request,
        name="runs.html",
        context={
            "request": request,
            "rows": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "scrape_targets": scrape_targets,
            "selected_scrape_ids": set(),
            "builtin_selected_ids": builtin_selected_ids,
            "builtin_selected_ids_json": json.dumps(sorted(builtin_selected_ids)),
        },
    )


@app.get("/tasks", response_class=HTMLResponse)
def tasks(request: Request, _: Any = Depends(_basic_auth)) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    rows = db.list_tasks()

    runtime_map = _TASKS.list_runtime()
    merged = []
    for t in rows:
        tid = str(t["task_id"])
        feishu_target_ids = db.get_task_target_ids(tid)
        scrape_target_ids = db.get_task_scrape_target_ids(tid)
        feishu_target_names = [tgt["name"] for tgt in db.get_task_targets(tid)]
        scrape_target_names = [tgt["name"] for tgt in db.get_task_scrape_targets(tid)]
        merged.append(
            {
                **t,
                "runtime": runtime_map.get(tid),
                "next_run_time": _TASKS.get_next_run_time(tid),
                "feishu_target_count": len(feishu_target_ids),
                "scrape_target_count": len(scrape_target_ids),
                "feishu_target_names": feishu_target_names,
                "scrape_target_names": scrape_target_names,
            }
        )
    db.close()
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="tasks.html",
        context={"request": request, "tasks": merged},
    )


@app.get("/tasks/new", response_class=HTMLResponse)
def task_new(request: Request, _: Any = Depends(_basic_auth)) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    all_targets = db.list_feishu_targets()
    scrape_targets = db.list_scrape_targets()
    db.close()
    builtin_names = {row["name"] for row in _load_builtin_verified_sites()}
    builtin_selected_ids = {
        str(t["target_id"])
        for t in scrape_targets
        if str(t["name"]) in builtin_names and bool(t.get("enabled"))
    }
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="task_new.html",
        context={
            "request": request,
            "all_targets": all_targets,
            "scrape_targets": scrape_targets,
            "form_data": _task_form_defaults(),
            "selected_ids": set(),
            "selected_scrape_ids": set(),
            "builtin_selected_ids": builtin_selected_ids,
            "builtin_selected_ids_json": json.dumps(sorted(builtin_selected_ids)),
            "form_action": "/tasks/create",
            "page_title": "新建任务",
            "submit_label": "创建",
        },
    )


def _truthy(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _parse_optional_int(raw: str) -> int | None:
    value = raw.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid integer: {raw}") from e


def _parse_bulk_scrape_targets(raw: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        if text.startswith("#"):
            continue
        parts = [p.strip() for p in re.split(r"\t|\|", text)]
        if len(parts) < 3:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"第 {index} 行格式错误，至少需要 名称、LIST_URL、BASE_URL，"
                    "可使用制表符或 | 分隔"
                ),
            )
        rows.append(
            {
                "name": parts[0],
                "list_url": parts[1],
                "base_url": parts[2],
                "keyword_regex": parts[3] if len(parts) >= 4 else "",
                "days_lookback": _parse_optional_int(parts[4])
                if len(parts) >= 5
                else None,
                "max_pages_total": _parse_optional_int(parts[5])
                if len(parts) >= 6
                else None,
                "max_pages_per_category": _parse_optional_int(parts[6])
                if len(parts) >= 7
                else None,
            }
        )
    return rows


def _builtin_verified_sites_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "已验证网站清单.md"


def _load_builtin_verified_sites() -> list[dict[str, object]]:
    path = _builtin_verified_sites_path()
    text = path.read_text(encoding="utf-8")
    rows = []
    for entry in parse_site_list_markdown(text):
        rows.append(
            {
                "name": entry.name,
                "list_url": entry.url,
                "base_url": _normalize_base_url(entry.url, entry.url),
                "keyword_regex": "",
                "days_lookback": None,
                "max_pages_total": None,
                "max_pages_per_category": None,
            }
        )
    return rows


def _config_to_task_form(task: dict[str, object], cfg: Config) -> dict[str, object]:
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    keyword_label = str(config.get("KEYWORDS_LABEL") or "").strip()
    return {
        "name": task.get("name") or "",
        "enabled": "true" if task.get("enabled") else "false",
        "schedule_type": task.get("schedule_type") or "cron",
        "cron_expr": task.get("cron_expr") or "0 8,12,16,20 * * *",
        "interval_seconds": task.get("interval_seconds") or 3600,
        "keywords": keyword_label,
        "days_lookback": config.get("DAYS_LOOKBACK", cfg.days_lookback),
        "dedupe_strategy": config.get("DEDUPE_STRATEGY", cfg.dedupe_strategy),
        "send_feishu": "false" if config.get("FEISHU_WEBHOOK_URL") == "" else "true",
        "feishu_notify_mode": config.get("FEISHU_NOTIFY_MODE", cfg.feishu_notify_mode),
        "max_items": config.get("MAX_ITEMS_PER_RUN", cfg.max_items_per_run),
        "loop_delay": config.get("LOOP_DELAY", cfg.loop_delay_seconds),
        "max_pages_total": config.get("MAX_PAGES_TOTAL", cfg.max_pages_total),
        "max_pages_per_category": config.get(
            "MAX_PAGES_PER_CATEGORY", cfg.max_pages_per_category
        ),
        "adaptive_threshold_pages": config.get(
            "ADAPTIVE_DELAY_THRESHOLD_PAGES", cfg.adaptive_delay_threshold_pages
        ),
        "batch_size": config.get("BATCH_SIZE", cfg.batch_size),
        "delay_increment_seconds": config.get(
            "DELAY_INCREMENT_SECONDS", cfg.delay_increment_seconds
        ),
        "max_loop_delay_seconds": config.get(
            "MAX_LOOP_DELAY_SECONDS", cfg.max_loop_delay_seconds
        ),
    }


def _task_form_defaults() -> dict[str, object]:
    return {
        "name": "每日采购",
        "enabled": "true",
        "schedule_type": "cron",
        "cron_expr": "0 8,12,16,20 * * *",
        "interval_seconds": 3600,
        "keywords": "采购",
        "days_lookback": 7,
        "dedupe_strategy": "title",
        "send_feishu": "true",
        "feishu_notify_mode": "digest",
        "max_items": 0,
        "loop_delay": 1,
        "max_pages_total": 80,
        "max_pages_per_category": 50,
        "adaptive_threshold_pages": 10,
        "batch_size": 50,
        "delay_increment_seconds": 1,
        "max_loop_delay_seconds": 10,
    }


def _build_task_payload(form: Any, cfg: Config) -> dict[str, object]:
    from apscheduler.triggers.cron import CronTrigger

    def _f(key: str, default: str = "") -> str:
        v = form.get(key)
        return str(v).strip() if v is not None else default

    def _fi(key: str, default: int) -> int:
        try:
            return int(_f(key, str(default)))
        except ValueError:
            return default

    def _ff(key: str, default: float) -> float:
        try:
            return float(_f(key, str(default)))
        except ValueError:
            return default

    name = _f("name")
    enabled = _f("enabled", "true")
    schedule_type = _f("schedule_type", "cron")
    cron_expr = _f("cron_expr", "0 8,12,16,20 * * *")
    interval_seconds = _fi("interval_seconds", 3600)
    keywords = _f("keywords", "采购")
    days_lookback = _fi("days_lookback", 7)
    dedupe_strategy = _f("dedupe_strategy", "title")
    send_feishu = _f("send_feishu", "true")
    feishu_notify_mode = _f("feishu_notify_mode", "digest")
    max_items = _fi("max_items", 0)
    loop_delay = _ff("loop_delay", 1.0)
    max_pages_total = _fi("max_pages_total", 200)
    max_pages_per_category = _fi("max_pages_per_category", 50)
    adaptive_threshold_pages = _fi("adaptive_threshold_pages", 10)
    batch_size = _fi("batch_size", 50)
    delay_increment_seconds = _ff("delay_increment_seconds", 1.0)
    max_loop_delay_seconds = _ff("max_loop_delay_seconds", 10.0)

    selected_target_ids = [str(t) for t in form.getlist("feishu_target_ids")]
    selected_scrape_target_ids = [str(t) for t in form.getlist("scrape_target_ids")]

    parts = [k.strip() for k in keywords.split(",") if k.strip()]
    keyword_regex = (
        "(" + "|".join(re.escape(p) for p in parts) + ")"
        if parts
        else cfg.keyword_regex
    )

    config: dict[str, object] = {
        "DAYS_LOOKBACK": max(1, days_lookback),
        "KEYWORD_REGEX": keyword_regex,
        "DEDUPE_STRATEGY": dedupe_strategy,
        "MAX_ITEMS_PER_RUN": max_items,
        "LOOP_DELAY": loop_delay,
        "MAX_PAGES_TOTAL": max(1, max_pages_total),
        "MAX_PAGES_PER_CATEGORY": max(1, max_pages_per_category),
        "ADAPTIVE_DELAY_THRESHOLD_PAGES": max(0, adaptive_threshold_pages),
        "BATCH_SIZE": max(1, batch_size),
        "DELAY_INCREMENT_SECONDS": max(0.0, delay_increment_seconds),
        "MAX_LOOP_DELAY_SECONDS": max(0.0, max_loop_delay_seconds),
        "AI_DISABLED": "false",
    }
    if parts:
        config["KEYWORDS_LABEL"] = ",".join(parts)
    notify_mode = feishu_notify_mode.strip().lower()
    if notify_mode not in {"digest", "per_item"}:
        notify_mode = "digest"
    config["FEISHU_NOTIFY_MODE"] = notify_mode
    if not _truthy(send_feishu):
        config["FEISHU_WEBHOOK_URL"] = ""

    st = schedule_type.strip().lower()
    if st not in {"cron", "interval"}:
        raise HTTPException(status_code=400, detail="invalid schedule_type")

    cron = None
    interval = None
    if st == "cron":
        cron = cron_expr.strip()
        if not cron:
            raise HTTPException(status_code=400, detail="cron_expr is required")
        try:
            CronTrigger.from_crontab(cron)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid cron_expr: {e}")
    else:
        if interval_seconds <= 0:
            raise HTTPException(
                status_code=400, detail="interval_seconds must be positive"
            )
        interval = interval_seconds

    return {
        "name": name,
        "enabled": _truthy(enabled),
        "schedule_type": st,
        "cron_expr": cron,
        "interval_seconds": interval,
        "config": config,
        "selected_target_ids": selected_target_ids,
        "selected_scrape_target_ids": selected_scrape_target_ids,
    }


@app.post("/tasks/create")
async def task_create(
    request: Request,
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    import uuid

    form = await request.form()

    cfg = Config.from_env()
    task_id = str(uuid.uuid4())
    payload = _build_task_payload(form, cfg)

    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    db.upsert_task(
        task_id=task_id,
        name=str(payload["name"] or task_id),
        enabled=bool(payload["enabled"]),
        schedule_type=str(payload["schedule_type"]),
        cron_expr=payload["cron_expr"],
        interval_seconds=payload["interval_seconds"],
        config=payload["config"],
    )
    db.set_task_targets(task_id, list(payload["selected_target_ids"]))
    db.set_task_scrape_targets(task_id, list(payload["selected_scrape_target_ids"]))
    db.close()

    _TASKS.sync_from_db()
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(
    request: Request, task_id: str, _: Any = Depends(_basic_auth)
) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    task = db.get_task(task_id)
    all_targets = db.list_feishu_targets()
    selected_ids = set(db.get_task_target_ids(task_id))
    all_scrape_targets = db.list_scrape_targets()
    selected_scrape_ids = set(db.get_task_scrape_target_ids(task_id))
    db.close()
    if not task:
        raise HTTPException(status_code=404)
    runtime = _TASKS.get_runtime(task_id)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="task_detail.html",
        context={
            "request": request,
            "task": task,
            "runtime": runtime,
            "all_targets": all_targets,
            "selected_ids": selected_ids,
            "all_scrape_targets": all_scrape_targets,
            "selected_scrape_ids": selected_scrape_ids,
        },
    )


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit(
    request: Request, task_id: str, _: Any = Depends(_basic_auth)
) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    task = db.get_task(task_id)
    all_targets = db.list_feishu_targets()
    scrape_targets = db.list_scrape_targets()
    selected_ids = set(db.get_task_target_ids(task_id))
    selected_scrape_ids = set(db.get_task_scrape_target_ids(task_id))
    db.close()
    if not task:
        raise HTTPException(status_code=404)
    builtin_names = {row["name"] for row in _load_builtin_verified_sites()}
    builtin_selected_ids = {
        str(t["target_id"])
        for t in scrape_targets
        if str(t["name"]) in builtin_names and bool(t.get("enabled"))
    }
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="task_edit.html",
        context={
            "request": request,
            "task": task,
            "all_targets": all_targets,
            "scrape_targets": scrape_targets,
            "selected_ids": selected_ids,
            "selected_scrape_ids": selected_scrape_ids,
            "builtin_selected_ids": builtin_selected_ids,
            "builtin_selected_ids_json": json.dumps(sorted(builtin_selected_ids)),
            "form_data": _config_to_task_form(task, cfg),
            "form_action": f"/tasks/{task_id}/edit",
            "page_title": "编辑任务",
            "submit_label": "保存",
        },
    )


@app.post("/tasks/{task_id}/edit")
async def task_edit_save(
    request: Request, task_id: str, _: Any = Depends(_basic_auth)
) -> RedirectResponse:
    cfg = Config.from_env()
    form = await request.form()
    payload = _build_task_payload(form, cfg)

    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    task = db.get_task(task_id)
    if not task:
        db.close()
        raise HTTPException(status_code=404)
    db.upsert_task(
        task_id=task_id,
        name=str(payload["name"] or task_id),
        enabled=bool(payload["enabled"]),
        schedule_type=str(payload["schedule_type"]),
        cron_expr=payload["cron_expr"],
        interval_seconds=payload["interval_seconds"],
        config=payload["config"],
    )
    db.set_task_targets(task_id, list(payload["selected_target_ids"]))
    db.set_task_scrape_targets(task_id, list(payload["selected_scrape_target_ids"]))
    db.close()

    _TASKS.sync_from_db()
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.post("/tasks/{task_id}/toggle")
def task_toggle(task_id: str, _: Any = Depends(_basic_auth)) -> RedirectResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    task = db.get_task(task_id)
    if not task:
        db.close()
        raise HTTPException(status_code=404)
    db.set_task_enabled(task_id, not bool(task.get("enabled")))
    db.close()
    _TASKS.sync_from_db()
    return RedirectResponse("/tasks", status_code=303)


@app.post("/tasks/{task_id}/run")
def task_run(task_id: str, _: Any = Depends(_basic_auth)) -> RedirectResponse:
    _TASKS.run_now(task_id)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.post("/tasks/{task_id}/stop")
def task_stop(task_id: str, _: Any = Depends(_basic_auth)) -> RedirectResponse:
    _TASKS.stop(task_id)
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.post("/tasks/{task_id}/delete")
def task_delete(task_id: str, _: Any = Depends(_basic_auth)) -> RedirectResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    db.delete_task(task_id)
    db.close()
    _TASKS.sync_from_db()
    return RedirectResponse("/tasks", status_code=303)


@app.post("/tasks/{task_id}/copy")
def task_copy(task_id: str, _: Any = Depends(_basic_auth)) -> RedirectResponse:
    import uuid

    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    task = db.get_task(task_id)
    if not task:
        db.close()
        raise HTTPException(status_code=404)

    new_task_id = str(uuid.uuid4())
    source_name = str(task.get("name") or task_id).strip()
    new_name = f"{source_name} 副本"
    db.upsert_task(
        task_id=new_task_id,
        name=new_name,
        enabled=bool(task.get("enabled")),
        schedule_type=str(task.get("schedule_type") or "cron"),
        cron_expr=task.get("cron_expr"),
        interval_seconds=task.get("interval_seconds"),
        config=dict(task.get("config") or {}),
    )
    db.set_task_targets(new_task_id, db.get_task_target_ids(task_id))
    db.set_task_scrape_targets(new_task_id, db.get_task_scrape_target_ids(task_id))
    db.close()

    _TASKS.sync_from_db()
    return RedirectResponse(f"/tasks/{new_task_id}", status_code=303)


@app.get("/tasks/{task_id}/stream")
def stream_task(task_id: str, _: Any = Depends(_basic_auth)) -> StreamingResponse:
    def gen():
        last = 0
        while True:
            rt = _TASKS.get_runtime(task_id)
            if not rt:
                yield "event: end\ndata: not_found\n\n"
                return
            lines = rt.lines
            while last < len(lines):
                yield f"data: {lines[last]}\n\n"
                last += 1
            if not rt.running and rt.last_status in {"COMPLETED", "FAILED"}:
                yield f"event: end\ndata: {rt.last_status}\n\n"
                return
            time.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(
    request: Request, run_id: str, _: Any = Depends(_basic_auth)
) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    row = db.get_run(run_id)
    db.close()

    live = _RUNS.get(run_id)
    log_file = _RUNS.get_log_file(run_id)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="run_detail.html",
        context={
            "request": request,
            "row": row,
            "run_id": run_id,
            "live": live,
            "log_file": log_file,
        },
    )


@app.post("/runs/start")
def start_run(
    days_lookback: int = Form(7),
    keywords: str = Form("采购"),
    dedupe_strategy: str = Form("title"),
    max_items: int = Form(0),
    loop_delay: float = Form(1.0),
    send_feishu: str = Form("true"),
    feishu_notify_mode: str = Form("digest"),
    max_pages_total: int = Form(200),
    max_pages_per_category: int = Form(50),
    adaptive_threshold_pages: int = Form(10),
    batch_size: int = Form(50),
    delay_increment_seconds: float = Form(1.0),
    max_loop_delay_seconds: float = Form(10.0),
    scrape_target_ids: list[str] = Form(default=[]),
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    overrides: dict[str, str] = {
        "DAYS_LOOKBACK": str(max(1, days_lookback)),
        "AI_DISABLED": "false",
        "DEDUPE_STRATEGY": dedupe_strategy,
        "MAX_ITEMS_PER_RUN": str(max_items),
        "LOOP_DELAY": str(loop_delay),
        "MAX_PAGES_TOTAL": str(max(1, max_pages_total)),
        "MAX_PAGES_PER_CATEGORY": str(max(1, max_pages_per_category)),
        "ADAPTIVE_DELAY_THRESHOLD_PAGES": str(max(0, adaptive_threshold_pages)),
        "BATCH_SIZE": str(max(1, batch_size)),
        "DELAY_INCREMENT_SECONDS": str(max(0.0, delay_increment_seconds)),
        "MAX_LOOP_DELAY_SECONDS": str(max(0.0, max_loop_delay_seconds)),
    }
    if send_feishu.strip().lower() not in {"1", "true", "yes", "on"}:
        overrides["FEISHU_WEBHOOK_URL"] = ""
    notify_mode = feishu_notify_mode.strip().lower()
    if notify_mode not in {"digest", "per_item"}:
        notify_mode = "digest"
    overrides["FEISHU_NOTIFY_MODE"] = notify_mode
    if keywords.strip():
        parts = [k.strip() for k in keywords.split(",") if k.strip()]
        if parts:
            overrides["KEYWORD_REGEX"] = (
                "(" + "|".join(re.escape(p) for p in parts) + ")"
            )
            overrides["KEYWORDS_LABEL"] = ",".join(parts)

    overrides["TASK_NAME"] = "WebUI 单次运行"

    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    selected_scrape_targets = [
        t for t in db.list_scrape_targets() if str(t.get("target_id")) in set(scrape_target_ids)
    ]
    db.close()
    if selected_scrape_targets:
        overrides["RUN_SCRAPE_TARGET_NAMES"] = "||".join(
            str(t.get("name") or "") for t in selected_scrape_targets
        )
        overrides["RUN_SCRAPE_TARGETS_JSON"] = json.dumps(
            [
                {
                    "name": str(t.get("name") or ""),
                    "list_url": str(t.get("list_url") or ""),
                    "base_url": str(t.get("base_url") or ""),
                    "keyword_regex": str(t.get("keyword_regex") or ""),
                    "days_lookback": t.get("days_lookback"),
                    "max_pages_total": t.get("max_pages_total"),
                    "max_pages_per_category": t.get("max_pages_per_category"),
                }
                for t in selected_scrape_targets
            ],
            ensure_ascii=False,
        )
    else:
        overrides["RUN_SCRAPE_TARGET_NAMES"] = (
            os.environ.get("LIST_URL", "https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html")
        )

    run_id = _RUNS.start(overrides)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@app.get("/runs/{run_id}/stream")
def stream_run(run_id: str, _: Any = Depends(_basic_auth)) -> StreamingResponse:
    def gen():
        last = 0
        while True:
            r = _RUNS.get(run_id)
            if not r:
                log_file = _RUNS.get_log_file(run_id)
                if not log_file:
                    yield "event: end\ndata: not_found\n\n"
                    return

                try:
                    with Path(log_file).open("r", encoding="utf-8") as f:
                        for line in f:
                            yield f"data: {line.rstrip('\n')}\n\n"
                except Exception:
                    yield "event: end\ndata: not_found\n\n"
                    return

                cfg = Config.from_env()
                db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
                row = db.get_run(run_id)
                db.close()
                yield f"event: end\ndata: {(row.get('status') if row else 'COMPLETED')}\n\n"
                return
            lines = r.lines
            while last < len(lines):
                yield f"data: {lines[last]}\n\n"
                last += 1
            if r.done:
                yield f"event: end\ndata: {r.status}\n\n"
                return
            time.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")


# ------------------------------------------------------------------ #
# Scrape targets management                                            #
# ------------------------------------------------------------------ #


@app.get("/settings/scrape-targets", response_class=HTMLResponse)
def scrape_targets_page(
    request: Request,
    saved: int = 0,
    imported: int = 0,
    builtin_imported: int = 0,
    _: Any = Depends(_basic_auth),
) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    targets = db.list_scrape_targets()
    db.close()
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="scrape_targets.html",
        context={
            "request": request,
            "targets": targets,
            "saved": saved == 1,
            "imported": imported,
            "builtin_imported": builtin_imported,
        },
    )


@app.post("/settings/scrape-targets")
async def scrape_target_create(
    request: Request,
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip()
    list_url = str(form.get("list_url", "")).strip()
    base_url = str(form.get("base_url", "")).strip()
    keyword_regex = str(form.get("keyword_regex", "")).strip()
    days_lookback = _parse_optional_int(str(form.get("days_lookback", "")))
    max_pages_total = _parse_optional_int(str(form.get("max_pages_total", "")))
    max_pages_per_category = _parse_optional_int(
        str(form.get("max_pages_per_category", ""))
    )
    enabled = _truthy(str(form.get("enabled", "true")))

    if not name:
        raise HTTPException(status_code=400, detail="站点名称不能为空")
    if not list_url:
        raise HTTPException(status_code=400, detail="LIST_URL 不能为空")

    base_url = base_url or _normalize_base_url(list_url, list_url)

    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    db.create_scrape_target(
        name=name,
        list_url=list_url,
        base_url=base_url,
        keyword_regex=keyword_regex,
        days_lookback=days_lookback,
        max_pages_total=max_pages_total,
        max_pages_per_category=max_pages_per_category,
        enabled=enabled,
    )
    db.close()
    return RedirectResponse("/settings/scrape-targets?saved=1", status_code=303)


@app.post("/settings/scrape-targets/import")
async def scrape_target_import(
    request: Request,
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    form = await request.form()
    raw = str(form.get("bulk_targets", "")).strip()
    if not raw:
        raise HTTPException(status_code=400, detail="批量导入内容不能为空")

    rows = _parse_bulk_scrape_targets(raw)
    if not rows:
        raise HTTPException(status_code=400, detail="未解析到可导入站点")

    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    for row in rows:
        db.create_scrape_target(
            name=str(row["name"]),
            list_url=str(row["list_url"]),
            base_url=str(row["base_url"]),
            keyword_regex=str(row["keyword_regex"]),
            days_lookback=row["days_lookback"],
            max_pages_total=row["max_pages_total"],
            max_pages_per_category=row["max_pages_per_category"],
            enabled=True,
        )
    db.close()
    return RedirectResponse(
        f"/settings/scrape-targets?imported={len(rows)}", status_code=303
    )


@app.post("/settings/scrape-targets/import-builtin")
def scrape_target_import_builtin(
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    rows = _load_builtin_verified_sites()
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    existing = {(str(t["name"]), str(t["list_url"])) for t in db.list_scrape_targets()}
    imported = 0
    for row in rows:
        key = (str(row["name"]), str(row["list_url"]))
        if key in existing:
            continue
        db.create_scrape_target(
            name=str(row["name"]),
            list_url=str(row["list_url"]),
            base_url=str(row["base_url"]),
            keyword_regex=str(row["keyword_regex"]),
            days_lookback=row["days_lookback"],
            max_pages_total=row["max_pages_total"],
            max_pages_per_category=row["max_pages_per_category"],
            enabled=True,
        )
        imported += 1
    db.close()
    return RedirectResponse(
        f"/settings/scrape-targets?builtin_imported={imported}", status_code=303
    )


@app.get("/settings/scrape-targets/{target_id}/edit", response_class=HTMLResponse)
def scrape_target_edit(
    request: Request,
    target_id: str,
    saved: int = 0,
    _: Any = Depends(_basic_auth),
) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    target = db.get_scrape_target(target_id)
    db.close()
    if not target:
        raise HTTPException(status_code=404)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="scrape_target_edit.html",
        context={"request": request, "target": target, "saved": saved == 1},
    )


@app.post("/settings/scrape-targets/{target_id}/edit")
async def scrape_target_edit_save(
    request: Request,
    target_id: str,
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip()
    list_url = str(form.get("list_url", "")).strip()
    base_url = str(form.get("base_url", "")).strip()
    keyword_regex = str(form.get("keyword_regex", "")).strip()
    days_lookback = _parse_optional_int(str(form.get("days_lookback", "")))
    max_pages_total = _parse_optional_int(str(form.get("max_pages_total", "")))
    max_pages_per_category = _parse_optional_int(
        str(form.get("max_pages_per_category", ""))
    )
    enabled = _truthy(str(form.get("enabled", "true")))

    if not name:
        raise HTTPException(status_code=400, detail="站点名称不能为空")
    if not list_url:
        raise HTTPException(status_code=400, detail="LIST_URL 不能为空")

    base_url = base_url or _normalize_base_url(list_url, list_url)

    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    if not db.get_scrape_target(target_id):
        db.close()
        raise HTTPException(status_code=404)
    db.update_scrape_target(
        target_id,
        name=name,
        list_url=list_url,
        base_url=base_url,
        keyword_regex=keyword_regex,
        days_lookback=days_lookback,
        max_pages_total=max_pages_total,
        max_pages_per_category=max_pages_per_category,
        enabled=enabled,
    )
    db.close()
    return RedirectResponse(
        f"/settings/scrape-targets/{target_id}/edit?saved=1", status_code=303
    )


@app.post("/settings/scrape-targets/{target_id}/toggle")
def scrape_target_toggle(
    target_id: str, _: Any = Depends(_basic_auth)
) -> RedirectResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    target = db.get_scrape_target(target_id)
    if not target:
        db.close()
        raise HTTPException(status_code=404)
    db.set_scrape_target_enabled(target_id, not bool(target.get("enabled")))
    db.close()
    return RedirectResponse("/settings/scrape-targets", status_code=303)


@app.post("/settings/scrape-targets/{target_id}/delete")
def scrape_target_delete(
    target_id: str, _: Any = Depends(_basic_auth)
) -> RedirectResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    db.delete_scrape_target(target_id)
    db.close()
    return RedirectResponse("/settings/scrape-targets", status_code=303)


# ------------------------------------------------------------------ #
# Feishu targets management                                            #
# ------------------------------------------------------------------ #


@app.get("/settings/feishu", response_class=HTMLResponse)
def feishu_targets_page(
    request: Request,
    saved: int = 0,
    _: Any = Depends(_basic_auth),
) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    targets = db.list_feishu_targets()
    db.close()
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="feishu_targets.html",
        context={"request": request, "targets": targets, "saved": saved == 1},
    )


@app.post("/settings/feishu")
async def feishu_target_create(
    request: Request,
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip()
    webhook_url = str(form.get("webhook_url", "")).strip()
    keyword_regex = str(form.get("keyword_regex", "")).strip()
    enabled = str(form.get("enabled", "true")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not name:
        raise HTTPException(status_code=400, detail="群名称不能为空")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL 不能为空")

    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    db.create_feishu_target(
        name=name,
        webhook_url=webhook_url,
        keyword_regex=keyword_regex,
        enabled=enabled,
    )
    db.close()
    return RedirectResponse("/settings/feishu?saved=1", status_code=303)


@app.get("/settings/feishu/{target_id}/edit", response_class=HTMLResponse)
def feishu_target_edit(
    request: Request,
    target_id: str,
    saved: int = 0,
    _: Any = Depends(_basic_auth),
) -> HTMLResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    target = db.get_feishu_target(target_id)
    db.close()
    if not target:
        raise HTTPException(status_code=404)
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="feishu_target_edit.html",
        context={"request": request, "target": target, "saved": saved == 1},
    )


@app.post("/settings/feishu/{target_id}/edit")
async def feishu_target_edit_save(
    request: Request,
    target_id: str,
    _: Any = Depends(_basic_auth),
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip()
    webhook_url = str(form.get("webhook_url", "")).strip()
    keyword_regex = str(form.get("keyword_regex", "")).strip()
    enabled = str(form.get("enabled", "true")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not name:
        raise HTTPException(status_code=400, detail="群名称不能为空")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL 不能为空")

    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    if not db.get_feishu_target(target_id):
        db.close()
        raise HTTPException(status_code=404)
    db.update_feishu_target(
        target_id,
        name=name,
        webhook_url=webhook_url,
        keyword_regex=keyword_regex,
        enabled=enabled,
    )
    db.close()
    return RedirectResponse(
        f"/settings/feishu/{target_id}/edit?saved=1", status_code=303
    )


@app.post("/settings/feishu/{target_id}/toggle")
def feishu_target_toggle(
    target_id: str, _: Any = Depends(_basic_auth)
) -> RedirectResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    target = db.get_feishu_target(target_id)
    if not target:
        db.close()
        raise HTTPException(status_code=404)
    db.set_target_enabled(target_id, not bool(target.get("enabled")))
    db.close()
    return RedirectResponse("/settings/feishu", status_code=303)


@app.post("/settings/feishu/{target_id}/delete")
def feishu_target_delete(
    target_id: str, _: Any = Depends(_basic_auth)
) -> RedirectResponse:
    cfg = Config.from_env()
    db = Database(cfg.db_path, dedupe_strategy=cfg.dedupe_strategy)
    db.delete_feishu_target(target_id)
    db.close()
    return RedirectResponse("/settings/feishu", status_code=303)
