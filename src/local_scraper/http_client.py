from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlsplit

import requests


@dataclass(frozen=True)
class HttpConfig:
    user_agent: str
    timeout_ms: int
    retry_count: int
    retry_interval_ms: int

    relay_zcpt_base_url: str | None = None
    relay_zcpt_token: str | None = None


class HttpClient:
    def __init__(self, cfg: HttpConfig):
        self._cfg = cfg
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": cfg.user_agent})

    def get_text(self, url: str) -> str:
        return self._get_text(url, allow_meta_refresh=True)

    def _get_text(self, url: str, allow_meta_refresh: bool) -> str:
        parts = urlsplit(url)
        if (
            self._cfg.relay_zcpt_base_url
            and parts.netloc == "zcpt.zgpmsm.com.cn"
            and parts.scheme in {"http", "https"}
        ):
            return self._get_text_via_zcpt_relay(parts)

        last_err: Exception | None = None
        for attempt in range(1, self._cfg.retry_count + 1):
            try:
                resp = self._session.get(url, timeout=self._cfg.timeout_ms / 1000)
                resp.raise_for_status()
                text = self._decode_response_text(resp)
                if allow_meta_refresh:
                    meta_url = self._extract_meta_refresh_url(text, url)
                    if meta_url and meta_url != url:
                        return self._get_text(meta_url, allow_meta_refresh=False)
                return text
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < self._cfg.retry_count:
                    time.sleep(self._cfg.retry_interval_ms / 1000)
                continue
        assert last_err is not None
        raise last_err

    def _decode_response_text(self, resp) -> str:
        headers = getattr(resp, "headers", {}) or {}
        content_type = (headers.get("Content-Type") or "").lower()
        m = re.search(r"charset=([\w\-]+)", content_type)
        if m:
            resp.encoding = m.group(1)
        elif not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text

    def _extract_meta_refresh_url(self, html: str, base_url: str) -> str | None:
        m = re.search(
            r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\'][^"\']*url=([^"\'>]+)',
            html,
            re.IGNORECASE,
        )
        if not m:
            return None
        return urljoin(base_url, m.group(1).strip())

    def _get_text_via_zcpt_relay(self, parts) -> str:
        relay_base = (self._cfg.relay_zcpt_base_url or "").rstrip("/")
        relay_url = relay_base + "/relay/zcpt/fetch"

        headers: dict[str, str] = {}
        if self._cfg.relay_zcpt_token:
            headers["Authorization"] = f"Bearer {self._cfg.relay_zcpt_token}"

        payload = {"path": parts.path or "/", "query": parts.query or ""}

        last_err: Exception | None = None
        for attempt in range(1, self._cfg.retry_count + 1):
            try:
                resp = self._session.post(
                    relay_url,
                    headers=headers,
                    json=payload,
                    timeout=self._cfg.timeout_ms / 1000,
                )
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or resp.encoding
                return resp.text
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < self._cfg.retry_count:
                    time.sleep(self._cfg.retry_interval_ms / 1000)
                continue
        assert last_err is not None
        raise last_err

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: Any,
        timeout_ms: int,
        retry_count: int,
        retry_interval_ms: int,
    ) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(1, retry_count + 1):
            try:
                resp = self._session.post(
                    url, headers=headers, json=payload, timeout=timeout_ms / 1000
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < retry_count:
                    time.sleep(retry_interval_ms / 1000)
                continue
        assert last_err is not None
        raise last_err

    def post_json_relaxed(
        self,
        url: str,
        headers: dict[str, str],
        payload: Any,
        timeout_ms: int,
    ) -> tuple[int | None, dict[str, Any] | None, str]:
        try:
            resp = self._session.post(
                url, headers=headers, json=payload, timeout=timeout_ms / 1000
            )
            text = self._decode_response_text(resp)
            try:
                return resp.status_code, resp.json(), text
            except Exception:
                return resp.status_code, None, text
        except Exception as e:  # noqa: BLE001
            return None, None, str(e)
