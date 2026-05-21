from __future__ import annotations

from local_scraper.ai_client import AiClient
from local_scraper.ai_client import AiConfig
from local_scraper.config import Config
from local_scraper.http_client import HttpClient
from local_scraper.http_client import HttpConfig


class _CaptureHttpClient(HttpClient):
    def __init__(self, content: str = "项目概要：测试摘要"):
        super().__init__(
            HttpConfig(
                user_agent="pytest",
                timeout_ms=1000,
                retry_count=1,
                retry_interval_ms=0,
            )
        )
        self.last_payload = None
        self.content = content

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload,
        timeout_ms: int,
        retry_count: int,
        retry_interval_ms: int,
    ):
        self.last_payload = payload
        return {
            "choices": [{"message": {"content": self.content}}],
        }


class _FallbackHttpClient(HttpClient):
    def __init__(self):
        super().__init__(
            HttpConfig(
                user_agent="pytest",
                timeout_ms=1000,
                retry_count=1,
                retry_interval_ms=0,
            )
        )
        self.models: list[str] = []

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload,
        timeout_ms: int,
        retry_count: int,
        retry_interval_ms: int,
    ):
        model = payload["model"]
        self.models.append(model)
        if model == "llama-3.3-70b-versatile":
            raise RuntimeError("429 rate_limit_exceeded")
        return {
            "choices": [{"message": {"content": "项目概要：兜底模型摘要"}}],
        }


def test_ai_client_prompt_prioritizes_decision_fields() -> None:
    http = _CaptureHttpClient()
    ai = AiClient(
        http,
        AiConfig(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            temperature=0.3,
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
        ),
    )

    summary = ai.summarize("这是一个关于猴车驱动装置配件采购的公告正文。")

    assert summary == "项目概要：测试摘要"
    user_prompt = http.last_payload["messages"][1]["content"]
    assert "优先输出你真正关心的决策信息" in user_prompt
    assert "采购内容/标的" in user_prompt
    assert "预算/限价" in user_prompt
    assert "报名截止时间、投标截止时间、开标时间" in user_prompt
    assert "联系人及电话" in user_prompt
    assert "项目周期" in user_prompt
    assert "应用场景、功能范围、建设内容" in user_prompt
    assert "压缩成一句业务摘要" in user_prompt
    assert "不要照抄公告原文的章节标题、编号串、表头、长句残片" in user_prompt


def test_config_defaults_to_available_ai_model(monkeypatch) -> None:
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_DISABLED", "false")
    monkeypatch.setenv("DRY_RUN", "false")

    cfg = Config.from_env()

    assert cfg.ai_model == "llama-3.3-70b-versatile"


def test_ai_client_falls_back_to_secondary_model_on_rate_limit() -> None:
    http = _FallbackHttpClient()
    ai = AiClient(
        http,
        AiConfig(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
        ),
    )

    summary = ai.summarize("测试正文")

    assert summary == "项目概要：兜底模型摘要"
    assert http.models == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def test_ai_client_filters_low_value_empty_fields() -> None:
    http = _CaptureHttpClient(
        "\n".join(
            [
                "项目概要：采购“人工智能+”智能招标采购系统升级及配套服务",
                "项目编号：ZPZB-26 Z106",
                "标段/包号：无",
                "交货期/服务期/工期：无",
                "预算/限价：498万元",
                "联系人：樊女士 0375-2787095",
            ]
        )
    )
    ai = AiClient(
        http,
        AiConfig(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            temperature=0.3,
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
        ),
    )

    summary = ai.summarize("测试正文")

    assert "项目概要：采购“人工智能+”智能招标采购系统升级及配套服务" in summary
    assert "项目编号：ZPZB-26 Z106" in summary
    assert "预算/限价：498万元" in summary
    assert "联系人：樊女士 0375-2787095" in summary
    assert "标段/包号：无" not in summary
    assert "交货期/服务期/工期：无" not in summary


def test_ai_client_removes_explanatory_prefix_lines() -> None:
    http = _CaptureHttpClient(
        "\n".join(
            [
                "根据原文内容，以下是结构化提要：",
                "项目概要：采购“人工智能+”智能招标采购系统升级及配套建设服务",
                "项目编号：ZPZB-26 Z106",
            ]
        )
    )
    ai = AiClient(
        http,
        AiConfig(
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="test-model",
            temperature=0.3,
            timeout_ms=1000,
            retry_count=1,
            retry_interval_ms=0,
        ),
    )

    summary = ai.summarize("测试正文")

    assert summary.startswith("项目概要：采购“人工智能+”智能招标采购系统升级及配套建设服务")
    assert "根据原文内容，以下是结构化提要：" not in summary
