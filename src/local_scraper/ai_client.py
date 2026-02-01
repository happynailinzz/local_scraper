from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .http_client import HttpClient


@dataclass(frozen=True)
class AiConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout_ms: int
    retry_count: int
    retry_interval_ms: int


class AiClient:
    def __init__(self, http: HttpClient, cfg: AiConfig):
        self._http = http
        self._cfg = cfg

    def summarize(self, content: str) -> str:
        clean = " ".join(content.split()).strip()
        clean = clean[:4000]

        messages = [
            {"role": "system", "content": "你是一个专业的招投标分析助手。"},
            {
                "role": "user",
                "content": (
                    "请总结以下公告内容。\n\n"
                    f"公告原文：{clean}\n\n"
                    "要求：\n"
                    "1. 提取项目名称、预算金额、截止日期、关键联系人（如有）。\n"
                    "2. 总结核心需求。\n"
                    "3. 输出格式简洁，字数控制在200字以内。"
                ),
            },
        ]

        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "temperature": self._cfg.temperature,
        }

        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }

        url = self._cfg.base_url.rstrip("/") + "/chat/completions"
        try:
            data = self._http.post_json(
                url=url,
                headers=headers,
                payload=payload,
                timeout_ms=self._cfg.timeout_ms,
                retry_count=self._cfg.retry_count,
                retry_interval_ms=self._cfg.retry_interval_ms,
            )
        except Exception:  # noqa: BLE001
            return "AI 总结失败"

        try:
            choices = data.get("choices") or []
            if not choices:
                return "AI 总结失败"
            msg = choices[0].get("message") or {}
            text = (msg.get("content") or "").strip()
            return text or "AI 总结失败"
        except Exception:  # noqa: BLE001
            return "AI 总结失败"
