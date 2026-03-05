from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .http_client import HttpClient


@dataclass(frozen=True)
class FeishuConfig:
    webhook_url: str
    timeout_ms: int
    retry_count: int
    retry_interval_ms: int


class FeishuClient:
    def __init__(self, http: HttpClient, cfg: FeishuConfig):
        self._http = http
        self._cfg = cfg

    def send_card(self, card_payload: dict[str, Any]) -> None:
        headers = {"Content-Type": "application/json"}
        self._http.post_json(
            url=self._cfg.webhook_url,
            headers=headers,
            payload=card_payload,
            timeout_ms=self._cfg.timeout_ms,
            retry_count=self._cfg.retry_count,
            retry_interval_ms=self._cfg.retry_interval_ms,
        )


def build_new_item_card(
    title: str, date: str, ai_summary: str, url: str
) -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "📢 发现新招标：" + title},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**发布日期**：{date}\n\n**AI 智能总结**：\n{ai_summary}",
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看原文"},
                            "url": url,
                            "type": "primary",
                        }
                    ],
                },
            ],
        },
    }


def build_summary_card(
    execution_time: str,
    duration_seconds: int,
    total_processed: int,
    total_new: int,
    total_duplicate: int,
) -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "template": "green",
                "title": {"tag": "plain_text", "content": "✅ 招采中心采集完成"},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**执行时间**：{execution_time}\n"
                            f"**耗时**：{duration_seconds}秒\n\n"
                            "**📊 统计数据**\n"
                            f"- 处理总数：{total_processed}\n"
                            f"- 新增数量：{total_new}\n"
                            f"- 重复数量：{total_duplicate}"
                        ),
                    },
                }
            ],
        },
    }


def build_error_card(timestamp: str, message: str) -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "template": "red",
                "title": {"tag": "plain_text", "content": "⚠️ 本地采集脚本出错"},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**错误时间**：{timestamp}\n\n**错误信息**：{message}",
                    },
                }
            ],
        },
    }


def build_digest_card(
    *,
    keyword_label: str,
    execution_time: str,
    duration_seconds: int,
    total_new: int,
    total_duplicate: int,
    total_processed: int,
    items: list[dict[str, str]],
    webui_public_url: str | None,
    days_lookback: int,
    image_url: str | None,
    range_start: int = 1,
    range_end: int = 1,
    total_items: int = 1,
) -> dict[str, Any]:
    shown = items[:10]
    rest = max(0, len(items) - len(shown))

    completion = f"新增{total_new}/重复{total_duplicate}/处理{total_processed}"
    header = (
        f"{execution_time} | {keyword_label} | {completion} | "
        f"第{range_start}-{range_end}/{total_items}"
    )

    elements: list[dict[str, Any]] = []
    if image_url:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"![banner]({image_url})",
                },
            }
        )
    elements.extend(
        [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**任务时间**：{execution_time}\n"
                        f"**耗时**：{duration_seconds}秒\n"
                        f"**关键词**：{keyword_label}\n"
                        f"**完成情况**：{completion}\n"
                        f"**回溯天数**：{days_lookback}"
                    ),
                },
            },
            {"tag": "hr"},
        ]
    )

    if shown:
        first = shown[0]
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**1. {first['title']}**\n"
                        f"发布日期：{first['date']}\n\n"
                        f"{first['ai_summary']}"
                    ),
                },
            }
        )
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看原文"},
                        "url": first["url"],
                        "type": "primary",
                    }
                ],
            }
        )

        if len(shown) > 1:
            elements.append({"tag": "hr"})
            for idx, it in enumerate(shown[1:], start=2):
                summary = _digest_summary(it.get("ai_summary", ""))
                elements.append(
                    {
                        "tag": "collapsible",
                        "expanded": False,
                        "header": {
                            "title": {
                                "tag": "plain_text",
                                "content": f"{idx}. {summary}",
                            }
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": (
                                        f"**{it['title']}**\n"
                                        f"发布日期：{it['date']}\n\n"
                                        f"{it['ai_summary']}\n\n"
                                        f"[查看原文]({it['url']})"
                                    ),
                                },
                            }
                        ],
                    }
                )
            if rest:
                elements.append(
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"……其余 {rest} 条略",
                        },
                    }
                )

    actions: list[dict[str, Any]] = []
    if webui_public_url:
        base = webui_public_url.rstrip("/")
        q = quote(keyword_label)
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看全部"},
                "url": f"{base}/announcements?q={q}",
                "type": "default",
            }
        )

    if actions:
        elements.append({"tag": "hr"})
        elements.append({"tag": "action", "actions": actions})

    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": header},
            },
            "elements": elements,
        },
    }


def build_feed_aggregate_card(
    *,
    total_count: int,
    channel_label: str,
    time_range: str,
    groups: list[dict[str, Any]],
    expanded_group_id: str | None = None,
) -> dict[str, Any]:
    """Build an "info feed" aggregate card (schema 2.0).

    The first group is expanded by default unless expanded_group_id is provided.

    groups item format:
      {
        "id": "group_id",
        "title": "...",
        "items": ["markdown line", ...]
      }

    Notes:
    - Uses built-in `collapsible` blocks so the card can be used with group-bot
      webhooks without an interactive callback server.
    - If you need "accordion" behavior (expand one group, collapse others), you
      must handle button callbacks and update the card server-side.
    """

    safe_total = max(0, int(total_count))
    channel = (channel_label or "").strip() or ""
    tr = (time_range or "").strip() or ""

    # Header row inside card body (left/right alignment).
    header_row: dict[str, Any] = {
        "tag": "column_set",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 3,
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{safe_total} 条** {channel}".strip(),
                        },
                    }
                ],
            },
            {
                "tag": "column",
                "width": "weighted",
                "weight": 2,
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": tr,
                        },
                    }
                ],
            },
        ],
    }

    elements: list[dict[str, Any]] = [header_row, {"tag": "hr"}]

    # Determine which group should be expanded.
    first_id = None
    for g in groups or []:
        gid = str(g.get("id") or "").strip()
        if gid:
            first_id = gid
            break
    expanded_id = (expanded_group_id or "").strip() or first_id

    for idx, g in enumerate(groups or []):
        gid = str(g.get("id") or "").strip() or f"group_{idx + 1}"
        title = str(g.get("title") or "").strip() or gid
        raw_items = g.get("items")
        item_lines = (
            [str(x) for x in raw_items]
            if isinstance(raw_items, list)
            else [str(raw_items)]
            if raw_items
            else []
        )
        body = "\n".join([ln for ln in (x.strip() for x in item_lines) if ln])
        if not body:
            body = "(无内容)"

        elements.append(
            {
                "tag": "collapsible",
                "expanded": bool(expanded_id and gid == expanded_id),
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": body},
                    }
                ],
            }
        )

    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "信息流聚合"},
            },
            "elements": elements,
        },
    }


def _digest_summary(text: str, max_len: int = 42) -> str:
    t = (text or "").replace("\n", " ").strip()
    if not t:
        return "(无摘要)"
    if len(t) <= max_len:
        return t
    return t[:max_len].rstrip() + "…"
