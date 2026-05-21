from __future__ import annotations

from local_scraper.fallback_summary import build_fallback_summary


def test_build_fallback_summary_extracts_bid_key_fields() -> None:
    title = "矿井人员定位系统升级改造项目招标公告"
    content = """
    项目名称：矿井人员定位系统升级改造项目。
    项目编号：XM-2026-001。
    招标人：平煤神马某矿业公司。
    招标代理机构：河南某招标代理有限公司。
    采购方式：公开招标。
    标段：1标段。
    服务期：签约后30日内完成供货安装。
    采购内容：人员定位系统、无线通信设备、安装调试服务。
    最高投标限价：120万元。
    报名开始时间：2026年04月18日09:00。
    报名截止时间：2026年04月22日17:00。
    获取招标文件时间：2026年04月18日09:00。
    投标截止时间：2026年04月25日09:30。
    开标时间：2026年04月25日09:30。
    实施地点：河南平顶山矿区。
    联系人：张工，联系电话：13800000000。
    """

    summary = build_fallback_summary(title, content)

    assert "项目概要：" in summary
    assert "项目编号：XM-2026-001" in summary
    assert "采购单位/招标人：平煤神马某矿业公司" in summary
    assert "代理机构：河南某招标代理有限公司" in summary
    assert "采购方式：公开招标" in summary
    assert "标段/包号：1标段" in summary
    assert "交货期/服务期/工期：签约后30日内完成供货安装" in summary
    assert "预算/限价：120万元" in summary
    assert "报名开始：2026-04-18 09:00" in summary
    assert "报名截止：2026-04-22 17:00" in summary
    assert "获取文件：2026-04-18 09:00" in summary
    assert "投标截止：2026-04-25 09:30" in summary
    assert "开标时间：2026-04-25 09:30" in summary
    assert "实施地点：河南平顶山矿区" in summary
    assert ("联系人：张工" in summary) or ("联系人：张工 13800000000" in summary)
    assert ("电话：13800000000" in summary) or ("联系人：张工 13800000000" in summary)


def test_build_fallback_summary_extracts_complex_ai_procurement_project() -> None:
    title = "平煤神马集团“人工智能+”智能招标采购项目招标公告"
    content = """
    项目名称：平煤神马集团“人工智能+”智能招标采购项目。
    招标编号：ZPZB-26 Z106。
    招标人：中国平煤神马控股集团有限公司招标采购中心。
    招标代理公司：河南中平招标有限公司。
    招标方式：公开招标。
    项目概况：采用通用大模型作为技术基座，结合集团电子招标采购平台现状及业务实际，选取12个应用场景进行建设。
    招标范围：建设具有招标文件智能编制、招标文件检测、开标、智能辅助评标、评标报告核验、辅助定标决策、中标合同签订、见证管理、档案管理、围串标识别、信用管理、协同监管等12项功能的“人工智能+”招标采购系统。
    项目周期：开发、部署建设期限为8个月、5个月部分功能上线，质保期2年。
    服务地点：中国平煤神马集团电子招标采购平台。
    最高投标限价：498万元。
    凡有意参加者，请于2026年04月16日08:00至2026年04月23日24:00获取招标文件。
    投标文件递交的截止时间（投标截止时间）为2026年05月07日09:00。
    开标时间：2026年05月07日09:00。
    联系人：采购一部电商采购科樊女士，联系电话：0375-2787095。
    联系人：招标部招标平台科陈女士，联系电话：0375-2787515。
    联系人：招标部招标平台科吕先生，联系电话：0375-2787613。
    """

    summary = build_fallback_summary(title, content, max_chars=800)

    assert "项目概要：建设基于大模型的“人工智能+”智能招标采购系统" in summary
    assert "项目编号：ZPZB-26 Z106" in summary
    assert "采购单位/招标人：中国平煤神马控股集团有限公司招标采购中心" in summary
    assert "代理机构：河南中平招标有限公司" in summary
    assert "采购方式：公开招标" in summary
    assert "采购内容：建设12个应用场景" in summary
    assert "项目周期：开发、部署建设期限为8个月、5个月部分功能上线，质保期2年" in summary
    assert "预算/限价：498万元" in summary
    assert "获取文件：2026-04-16 08:00" in summary
    assert "投标截止：2026-05-07 09:00" in summary
    assert "开标时间：2026-05-07 09:00" in summary
    assert "实施地点：中国平煤神马集团电子招标采购平台" in summary
    assert "联系人：樊女士 0375-2787095；陈女士 0375-2787515；吕先生 0375-2787613" in summary
