from __future__ import annotations

import re


_RE_BUDGET = re.compile(
    r"预算(?:金额)?[:：\s]*([0-9]+(?:\.[0-9]+)?\s*(?:万元|万|元|人民币|RMB)?)"
)
_RE_DEADLINE = re.compile(
    r"(?:投标|报名)?截止(?:日期|时间)?[:：\s]*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日\s*[0-9]{1,2}:[0-9]{2})"
)
_RE_PHONE = re.compile(r"(\d{3,4}-\d{7,8}|1\d{10})")
_RE_CONTACT = re.compile(r"联系人[:：\s]*([\u4e00-\u9fff]{1,6})")


def build_fallback_summary(title: str, content: str, max_chars: int = 200) -> str:
    """Best-effort summary when AI is disabled/unavailable.

    The goal is not perfect extraction; just something useful and stable.
    """

    text = " ".join(content.split())
    budget = _RE_BUDGET.search(text)
    deadline = _RE_DEADLINE.search(text)
    contact = _RE_CONTACT.search(text)
    phone = _RE_PHONE.search(text)

    parts: list[str] = [f"项目名称：{title}"]
    if budget:
        parts.append(f"预算金额：{budget.group(1)}")
    if deadline:
        parts.append(f"截止日期：{deadline.group(1)}")
    if contact:
        parts.append(f"联系人：{contact.group(1)}")
    if phone:
        parts.append(f"电话：{phone.group(1)}")

    out = "\n".join(parts)
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out
