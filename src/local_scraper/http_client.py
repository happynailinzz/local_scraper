from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import requests


@dataclass(frozen=True)
class HttpConfig:
    user_agent: str
    timeout_ms: int
    retry_count: int
    retry_interval_ms: int


class HttpClient:
    def __init__(self, cfg: HttpConfig):
        self._cfg = cfg
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": cfg.user_agent})

    def get_text(self, url: str) -> str:
        last_err: Exception | None = None
        for attempt in range(1, self._cfg.retry_count + 1):
            try:
                resp = self._session.get(url, timeout=self._cfg.timeout_ms / 1000)
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
