from __future__ import annotations

import pytest
from fastapi import HTTPException

from local_scraper.web import app as web_app


def test_normalize_base_url() -> None:
    assert (
        web_app._normalize_base_url(
            "https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html",
            "https://fallback.example.com",
        )
        == "https://zcpt.zgpmsm.com.cn"
    )
    assert (
        web_app._normalize_base_url("invalid-url", "https://fallback.example.com")
        == "https://fallback.example.com"
    )


def test_save_and_load_env_config(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    monkeypatch.setattr(web_app, "_ENV_FILE", env_path)

    web_app._save_env_config(
        {
            "LIST_URL": "https://example.com/list.html",
            "AI_MODEL": "gpt-4.1-mini",
            "FEISHU_WEBHOOK_URL": "",
        }
    )

    loaded = web_app._load_env_config()
    assert loaded["LIST_URL"] == "https://example.com/list.html"
    assert loaded["AI_MODEL"] == "gpt-4.1-mini"
    assert loaded["FEISHU_WEBHOOK_URL"] == ""


def test_init_settings_save_custom_model(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    monkeypatch.setattr(web_app, "_ENV_FILE", env_path)

    response = web_app.init_settings_save(
        list_url="https://example.com/list.html",
        base_url="",
        feishu_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/abc",
        feishu_notify_mode="per_item",
        ai_base_url="https://api.example.com/v1",
        ai_model_preset="custom",
        ai_model_custom="my-custom-model",
        ai_api_key="sk-test",
        ai_disabled="false",
        _=None,
    )

    loaded = web_app._load_env_config()
    assert response.status_code == 303
    assert response.headers["location"] == "/settings/init?saved=1"
    assert loaded["BASE_URL"] == "https://example.com"
    assert loaded["FEISHU_NOTIFY_MODE"] == "per_item"
    assert loaded["AI_MODEL"] == "my-custom-model"


def test_init_settings_save_requires_api_key_when_ai_enabled(
    tmp_path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    monkeypatch.setattr(web_app, "_ENV_FILE", env_path)

    with pytest.raises(HTTPException) as ex:
        web_app.init_settings_save(
            list_url="https://example.com/list.html",
            base_url="https://example.com",
            feishu_webhook_url="",
            feishu_notify_mode="digest",
            ai_base_url="https://api.example.com/v1",
            ai_model_preset="gpt-4.1-mini",
            ai_model_custom="",
            ai_api_key="",
            ai_disabled="false",
            _=None,
        )

    assert ex.value.status_code == 400
