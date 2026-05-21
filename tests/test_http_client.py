from __future__ import annotations

from local_scraper.http_client import HttpClient, HttpConfig


class _FakeResponse:
    def __init__(
        self,
        text: str,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self._text = text.encode("utf-8")
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.encoding = None
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    @property
    def text(self) -> str:
        encoding = self.encoding or "utf-8"
        return self._text.decode(encoding, errors="ignore")

    def json(self):
        import json

        return json.loads(self.text)


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]):
        self.responses = responses
        self.calls: list[str] = []
        self.headers = {}

    def get(self, url: str, timeout: float):
        self.calls.append(url)
        return self.responses.pop(0)

    def post(self, url: str, headers: dict[str, str], json, timeout: float):
        self.calls.append(url)
        return self.responses.pop(0)


def test_http_client_follows_meta_refresh() -> None:
    client = HttpClient(
        HttpConfig(
            user_agent="pytest",
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
        )
    )
    client._session = _FakeSession(
        [
            _FakeResponse(
                '<meta http-equiv="Refresh" content="0; URL=/cms/index.htm?v=0">'
            ),
            _FakeResponse("<html><body>ok</body></html>"),
        ]
    )

    text = client.get_text("http://www.zmzb.com/")

    assert "ok" in text
    assert client._session.calls == [
        "http://www.zmzb.com/",
        "http://www.zmzb.com/cms/index.htm?v=0",
    ]


def test_http_client_post_json_relaxed() -> None:
    client = HttpClient(
        HttpConfig(
            user_agent="pytest",
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
        )
    )
    client._session = _FakeSession(
        [
            _FakeResponse(
                '{"code":603,"msg":"登录信息失效，请重新登录"}',
                headers={"Content-Type": "application/json;charset=utf-8"},
            )
        ]
    )

    status, payload, text = client.post_json_relaxed(
        "https://example.com/api",
        headers={},
        payload={},
        timeout_ms=1000,
    )

    assert status == 200
    assert payload == {"code": 603, "msg": "登录信息失效，请重新登录"}
    assert "登录信息失效" in text
