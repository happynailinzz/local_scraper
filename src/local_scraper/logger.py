from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any
import json


_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class Logger:
    enabled: bool = True
    json_mode: bool = False
    level: str = "info"

    def _level_value(self) -> int:
        v = (self.level or "info").strip().lower()
        return {
            "debug": 10,
            "info": 20,
            "warn": 30,
            "warning": 30,
            "error": 40,
        }.get(v, 20)

    def _should_emit(self, level: str) -> bool:
        if not self.enabled:
            return False
        return {
            "DEBUG": 10,
            "INFO": 20,
            "WARN": 30,
            "ERROR": 40,
        }[level] >= self._level_value()

    def _ts(self) -> str:
        return datetime.now(tz=_TZ).isoformat(timespec="seconds")

    def info(self, event: str, **fields: Any) -> None:
        self._emit("INFO", event, **fields)

    def warn(self, event: str, **fields: Any) -> None:
        self._emit("WARN", event, **fields)

    def debug(self, event: str, **fields: Any) -> None:
        self._emit("DEBUG", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit("ERROR", event, **fields)

    def _emit(self, level: str, event: str, **fields: Any) -> None:
        if not self._should_emit(level):
            return
        if self.json_mode:
            payload = {"ts": self._ts(), "level": level, "event": event, **fields}
            print(json.dumps(payload, ensure_ascii=False))
        else:
            suffix = ""
            if fields:
                parts = []
                for k, v in fields.items():
                    if v is None:
                        continue
                    parts.append(f"{k}={v}")
                if parts:
                    suffix = " " + " ".join(parts)
            print(f"[{self._ts()}] {level} {event}{suffix}")
