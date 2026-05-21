from __future__ import annotations

import pytest

from local_scraper.feishu_client import FeishuClient
from local_scraper.feishu_client import FeishuConfig
from local_scraper.http_client import HttpClient
from local_scraper.http_client import HttpConfig


class _StubHttpClient(HttpClient):
    def __init__(self, response: dict[str, object]):
        super().__init__(
            HttpConfig(
                user_agent="pytest",
                timeout_ms=1000,
                retry_count=1,
                retry_interval_ms=0,
            )
        )
        self.response = response

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload,
        timeout_ms: int,
        retry_count: int,
        retry_interval_ms: int,
    ) -> dict[str, object]:
        return self.response


def test_feishu_client_raises_when_business_code_is_not_zero() -> None:
    client = FeishuClient(
        _StubHttpClient({"code": 19024, "msg": "Key Words Not Found"}),
        FeishuConfig(
            webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
        ),
    )

    with pytest.raises(RuntimeError, match="19024.*Key Words Not Found"):
        client.send_card({"msg_type": "text", "content": {"text": "test"}})
