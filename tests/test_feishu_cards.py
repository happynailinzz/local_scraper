from __future__ import annotations

from local_scraper.feishu_client import build_digest_card
from local_scraper.feishu_client import build_new_item_card


def test_build_new_item_card_renders_structured_summary() -> None:
    summary = "\n".join(
        [
            "项目概要：采购矿井人员定位系统升级及配套安装服务",
            "项目编号：XM-2026-001",
            "采购单位/招标人：平煤神马某矿业公司",
            "代理机构：河南某招标代理有限公司",
            "采购方式：公开招标",
            "标段/包号：1标段",
            "交货期/服务期/工期：签约后30日内完成供货安装",
            "预算/限价：120万元",
            "报名截止：2026-04-22 17:00",
            "投标截止：2026-04-25 09:30",
            "开标时间：2026-04-25 09:30",
        ]
    )
    card = build_new_item_card(
        title="矿井人员定位系统升级改造项目招标公告",
        date="2026-04-19",
        ai_summary=summary,
        url="https://example.com/notice/1",
    )
    content = card["card"]["elements"][0]["text"]["content"]
    assert "**项目概要**" in content
    assert "- 项目编号：XM-2026-001" in content
    assert "- 采购单位/招标人：平煤神马某矿业公司" in content
    assert "- 代理机构：河南某招标代理有限公司" in content
    assert "- 采购方式：公开招标" in content
    assert "- 标段/包号：1标段" in content
    assert "- **报名截止**：2026-04-22 17:00" in content
    assert "- **投标截止**：2026-04-25 09:30" in content


def test_build_digest_card_renders_highlighted_summary() -> None:
    summary = "\n".join(
        [
            "项目概要：采购矿井人员定位系统升级及配套安装服务",
            "项目编号：XM-2026-001",
            "采购单位/招标人：平煤神马某矿业公司",
            "代理机构：河南某招标代理有限公司",
            "采购方式：公开招标",
            "标段/包号：1标段",
            "交货期/服务期/工期：签约后30日内完成供货安装",
            "预算/限价：120万元",
            "报名截止：2026-04-22 17:00",
            "投标截止：2026-04-25 09:30",
        ]
    )
    card = build_digest_card(
        keyword_label="信息化",
        execution_time="2026-04-19 12:00:00",
        duration_seconds=12,
        total_new=1,
        total_duplicate=0,
        total_processed=1,
        items=[
            {
                "title": "矿井人员定位系统升级改造项目招标公告",
                "date": "2026-04-19",
                "ai_summary": summary,
                "url": "https://example.com/notice/1",
            }
        ],
        webui_public_url=None,
        days_lookback=7,
        image_url=None,
    )
    content = card["card"]["elements"][2]["text"]["content"]
    assert "**项目概要**" in content
    assert "- 项目编号：XM-2026-001" in content
    assert "- 采购单位/招标人：平煤神马某矿业公司" in content
    assert "- 代理机构：河南某招标代理有限公司" in content
    assert "- 采购方式：公开招标" in content
    assert "- 标段/包号：1标段" in content
    assert "- **预算/限价**：120万元" in content
    assert "- **报名截止**：2026-04-22 17:00" in content


def test_build_new_item_card_cleans_noisy_ai_summary() -> None:
    summary = "\n".join(
        [
            "项目概要：中平能化集团天工机械制造有限公司采购项目采购信息公示 一、项目名称：中平能化集团天工机械制造有限公司2026年04月20日采购项目猴车驱动装置配件-辅助厂 二、项目类别：材料类 三、",
            "项目编号：JXZBXJ2026042009-1",
            "采购单位/招标人：中平能化集团天工机械制造有限公司 六、采购内容与最高限价: 行项目编号 物料编码 物料名称 规格 型号 税率(%) 技术",
            "采购方式：询比采购 五、采购人：中平能化集团天工机械制造有限公司 六、",
            "电话：13301000002",
            "项目名称：[询比价] JXZBXJ2026042009-1中平能化集团天工机械制造有限公司2026年04月20日采购项目猴车驱动装置配件-辅助厂采购公告",
        ]
    )

    card = build_new_item_card(
        title="[询比价] JXZBXJ2026042009-1中平能化集团天工机械制造有限公司2026年04月20日采购项目猴车驱动装置配件-辅助厂采购公告",
        date="2026-04-21",
        ai_summary=summary,
        url="https://example.com/notice/2",
    )

    content = card["card"]["elements"][0]["text"]["content"]
    assert "**项目概要**：猴车驱动装置配件采购项目" in content
    assert "- 项目编号：JXZBXJ2026042009-1" in content
    assert "- 采购单位/招标人：中平能化集团天工机械制造有限公司" in content
    assert "- 采购方式：询比采购" in content
    assert "- 电话：13301000002" in content
    assert "采购内容与最高限价" not in content
    assert "行项目编号 物料编码" not in content
    assert "五、采购人" not in content
