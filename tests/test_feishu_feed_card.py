from __future__ import annotations


from local_scraper.feishu_client import build_feed_aggregate_card


def test_build_feed_aggregate_card_expands_first_group_by_default() -> None:
    payload = build_feed_aggregate_card(
        total_count=134,
        channel_label="Twitter",
        time_range="26/02/02 19-20",
        groups=[
            {
                "id": "giant_finance",
                "title": "大厂 & 融资：SpaceX 洽谈…",
                "items": [
                    "• **SpaceX 洽谈合并 xAI**：[Bloomberg](https://example.com) 简述",
                    "• **Thrive 投资 1 亿美元**：[Bloomberg](https://example.com) 简述",
                ],
            },
            {
                "id": "model_paper",
                "title": "模型 & 论文：Claude Sonnet 5 泄露…",
                "items": ["• **Claude Sonnet 5**：..."],
            },
        ],
    )

    assert payload["msg_type"] == "interactive"
    assert payload["card"]["schema"] == "2.0"

    elements = payload["card"]["elements"]
    collapsibles = [e for e in elements if e.get("tag") == "collapsible"]
    assert len(collapsibles) == 2
    assert collapsibles[0]["expanded"] is True
    assert collapsibles[1]["expanded"] is False


def test_build_feed_aggregate_card_expands_group_by_id() -> None:
    payload = build_feed_aggregate_card(
        total_count=2,
        channel_label="X",
        time_range="t",
        groups=[
            {"id": "a", "title": "A", "items": ["1"]},
            {"id": "b", "title": "B", "items": ["2"]},
        ],
        expanded_group_id="b",
    )

    elements = payload["card"]["elements"]
    collapsibles = [e for e in elements if e.get("tag") == "collapsible"]
    assert len(collapsibles) == 2
    assert collapsibles[0]["expanded"] is False
    assert collapsibles[1]["expanded"] is True
