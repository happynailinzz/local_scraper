from __future__ import annotations


from local_scraper.http_client import HttpClient, HttpConfig


class _FakeResponse:
    def __init__(self, *, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.last_post: dict[str, object] | None = None
        self.last_get: dict[str, object] | None = None

    def get(self, url: str, timeout: float) -> _FakeResponse:  # noqa: ARG002
        self.last_get = {"url": url}
        return _FakeResponse(text="direct")

    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: object,
        timeout: float,  # noqa: ARG002
    ) -> _FakeResponse:
        self.last_post = {"url": url, "headers": headers, "json": json}
        return _FakeResponse(text="via-relay")


def test_http_client_uses_zcpt_relay_when_configured(monkeypatch) -> None:
    fake = _FakeSession()
    monkeypatch.setattr(
        "local_scraper.http_client.requests.Session",
        lambda: fake,
    )

    http = HttpClient(
        HttpConfig(
            user_agent="pytest",
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
            relay_zcpt_base_url="https://cn-relay.example.com",
            relay_zcpt_token="tok",
        )
    )

    out = http.get_text("https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html?pageIndex=2")
    assert out == "via-relay"
    assert fake.last_get is None
    assert fake.last_post is not None
    assert fake.last_post["url"] == "https://cn-relay.example.com/relay/zcpt/fetch"
    assert fake.last_post["headers"] == {"Authorization": "Bearer tok"}
    assert fake.last_post["json"] == {
        "path": "/jyxx/sec_listjyxx.html",
        "query": "pageIndex=2",
    }


def test_http_client_falls_back_to_direct_for_other_hosts(monkeypatch) -> None:
    fake = _FakeSession()
    monkeypatch.setattr(
        "local_scraper.http_client.requests.Session",
        lambda: fake,
    )

    http = HttpClient(
        HttpConfig(
            user_agent="pytest",
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
            relay_zcpt_base_url="https://cn-relay.example.com",
            relay_zcpt_token="tok",
        )
    )

    out = http.get_text("https://example.com/")
    assert out == "direct"
    assert fake.last_get == {"url": "https://example.com/"}
    assert fake.last_post is None
