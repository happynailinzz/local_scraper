from __future__ import annotations

from pathlib import Path

from local_scraper.parser import (
    parse_ccgp_list_page,
    parse_chinabidding_cn_homepage,
    parse_chinabidding_cn_list_page,
    parse_cuecp_api_payload,
    parse_dlztb_list_page,
    parse_generic_list_page,
    parse_henan_notice_page,
    parse_list_page,
    parse_category_links,
    parse_next_page_url,
    parse_powerec_content_api_payload,
    parse_jszhaobiao_search_page,
    parse_qianlima_list_page,
    parse_site_list_markdown,
)


def test_parse_list_page_fixture() -> None:
    html = (
        Path(__file__).resolve().parent / "fixtures" / "sample_list.html"
    ).read_text(encoding="utf-8")
    items = parse_list_page(html)
    assert len(items) == 5
    assert items[0].title
    assert items[0].link.startswith("/")
    assert "2026" in items[0].date_raw


def test_parse_site_list_markdown() -> None:
    markdown = """
| 名称 | 官网主页 |
| --- | --- |
| 站点A | [https://a.example.com](https://a.example.com) |
| 站点B | [https://b.example.com](https://b.example.com) / [https://b2.example.com](https://b2.example.com) |
"""
    entries = parse_site_list_markdown(markdown)
    assert [(it.name, it.url) for it in entries] == [
        ("站点A", "https://a.example.com"),
        ("站点B", "https://b.example.com"),
        ("站点B", "https://b2.example.com"),
    ]


def test_parse_generic_list_page() -> None:
    html = """
    <html><body>
      <ul>
        <li><a href="/detail/1.html">AI 平台采购项目</a><span>发布时间：2026-04-10</span></li>
        <li><a href="/detail/2.html">系统升级服务</a><span>2026/04/09</span></li>
      </ul>
    </body></html>
    """
    items = parse_generic_list_page(html, current_url="https://example.com/list")
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        ("AI 平台采购项目", "https://example.com/detail/1.html", "2026-04-10"),
        ("系统升级服务", "https://example.com/detail/2.html", "2026-04-09"),
    ]


def test_parse_ccgp_list_page() -> None:
    html = """
    <ul>
      <li><a href="news/202604/t20260412_1.htm">某单位采购公告</a><span>2026-04-12</span></li>
      <li><a href="news/202604/t20260411_2.htm">某系统招标公告</a><span>2026/04/11</span></li>
    </ul>
    """
    items = parse_ccgp_list_page(html, current_url="http://www.ccgp.gov.cn/")
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "某单位采购公告",
            "http://www.ccgp.gov.cn/news/202604/t20260412_1.htm",
            "2026-04-12",
        ),
        (
            "某系统招标公告",
            "http://www.ccgp.gov.cn/news/202604/t20260411_2.htm",
            "2026-04-11",
        ),
    ]


def test_parse_ccgp_list_page_extracts_date_from_href() -> None:
    html = """
    <ul>
      <li><a href="/cggg/zygg/gkzb/202604/t20260412_26393034.htm">华东师范大学校园网基础设施改造公开招标公告</a></li>
    </ul>
    """
    items = parse_ccgp_list_page(html, current_url="http://www.ccgp.gov.cn/")
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "华东师范大学校园网基础设施改造公开招标公告",
            "http://www.ccgp.gov.cn/cggg/zygg/gkzb/202604/t20260412_26393034.htm",
            "2026-04-12",
        )
    ]


def test_parse_generic_list_page_handles_henan_transaction_notice() -> None:
    html = """
    <div>
      <a href="/jyxx/002002/002002001/20260417/d50080b3-3f4b-4785-a29d-20ef8d232ad6.html">
        [河南省·新乡市·新乡市] 新乡市红旗区机关事务中心海关东办公区物业服务项目-公开招标公告
      </a>
      <span>2026-04-17</span>
    </div>
    """
    items = parse_generic_list_page(
        html,
        current_url="http://hnsggzyjy.henan.gov.cn/jyxx/transaction_notice.html",
    )
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "[河南省·新乡市·新乡市] 新乡市红旗区机关事务中心海关东办公区物业服务项目-公开招标公告",
            "http://hnsggzyjy.henan.gov.cn/jyxx/002002/002002001/20260417/d50080b3-3f4b-4785-a29d-20ef8d232ad6.html",
            "2026-04-17",
        )
    ]


def test_parse_henan_notice_page_extracts_links_and_dates() -> None:
    html = """
    <div>
      <a href="/jyxx/002002/002002001/20260417/d50080b3-3f4b-4785-a29d-20ef8d232ad6.html">
        [河南省·新乡市·新乡市] 新乡市红旗区机关事务中心海关东办公区物业服务项目-公开招标公告
      </a>
      <span>2026-04-17</span>
    </div>
    <div>
      <a href="/jyxx/002001/002001001/20260417/fd7bdb47-1084-41af-bcfa-3a28101d1481.html">
        新疆哈密市伊吾工业园区配套物流园供暖、排水管网建设项目（施工）
      </a>
    </div>
    """
    items = parse_henan_notice_page(
        html,
        current_url="http://hnsggzyjy.henan.gov.cn/jyxx/transaction_notice.html",
    )
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "[河南省·新乡市·新乡市] 新乡市红旗区机关事务中心海关东办公区物业服务项目-公开招标公告",
            "http://hnsggzyjy.henan.gov.cn/jyxx/002002/002002001/20260417/d50080b3-3f4b-4785-a29d-20ef8d232ad6.html",
            "2026-04-17",
        ),
        (
            "新疆哈密市伊吾工业园区配套物流园供暖、排水管网建设项目（施工）",
            "http://hnsggzyjy.henan.gov.cn/jyxx/002001/002001001/20260417/fd7bdb47-1084-41af-bcfa-3a28101d1481.html",
            "2026-04-17",
        ),
    ]


def test_parse_cuecp_api_payload() -> None:
    payload = """
    {
      "success": true,
      "data": {
        "bidBeans": [
          {
            "id": "abc123",
            "noticeTitle": "2026年中国联通国际HKDC2外部审计服务项目公告",
            "startTime": "2026-04-10"
          }
        ]
      }
    }
    """
    items = parse_cuecp_api_payload(payload, current_url="https://www.cuecp.cn/")
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "2026年中国联通国际HKDC2外部审计服务项目公告",
            "https://www.cuecp.cn/#/notice/abc123",
            "2026-04-10",
        )
    ]


def test_parse_powerec_content_api_payload() -> None:
    payload = """
    {
      "msg": "操作成功",
      "res": {
        "rows": [
          {
            "title": "晋能控股集团有限公司潘家窑煤矿项目",
            "url": "/1ywgg1/20260409/1226942635323686912.html",
            "publishDate": "2026-04-09T17:12:00.000+0800"
          }
        ]
      }
    }
    """
    items = parse_powerec_content_api_payload(
        payload,
        current_url="https://dzzb.jnkgjtdzzbgs.com/cms/default/webfile/1ywgg1/index.html",
    )
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "晋能控股集团有限公司潘家窑煤矿项目",
            "https://dzzb.jnkgjtdzzbgs.com/1ywgg1/20260409/1226942635323686912.html",
            "2026-04-09",
        )
    ]


def test_parse_qianlima_list_page() -> None:
    html = """
    <div class="list-single">
      <div class="f-v-center list-left hover-text_theme">
        <a href="https://www.qianlima.com/bid-588812283.html" class="title">郑州高新供水有限责任公司无人机采购询比公告</a>
      </div>
      <div class="time-block width--100">2026-04-13</div>
    </div>
    """
    items = parse_qianlima_list_page(html, current_url="https://www.qianlima.com/zbgg/")
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "郑州高新供水有限责任公司无人机采购询比公告",
            "https://www.qianlima.com/bid-588812283.html",
            "2026-04-13",
        )
    ]


def test_parse_chinabidding_cn_homepage() -> None:
    html = """
    <div class="notice-item">
      <div class="item-left">
        <a href="https://www.chinabidding.cn/zbgg/U-vztTdZM.html">撞击解体试验诊断测试耗材</a>
      </div>
      <div class="item-right">2026-04-10</div>
    </div>
    """
    items = parse_chinabidding_cn_homepage(
        html, current_url="https://www.chinabidding.com.cn/"
    )
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "撞击解体试验诊断测试耗材",
            "https://www.chinabidding.cn/zbgg/U-vztTdZM.html",
            "2026-04-10",
        )
    ]


def test_parse_dlztb_list_page() -> None:
    html = """
    <div class="item">
      <a href="http://www.dlztb.com/zbgg/202604/57149.html">华润电力(渤海新区)有限公司两台机组低压末级叶片喷丸强化项目单源直接采购结果公告</a>
      <span>04-13</span>
    </div>
    """
    items = parse_dlztb_list_page(html, current_url="http://www.dlztb.com/zbgg/")
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "华润电力(渤海新区)有限公司两台机组低压末级叶片喷丸强化项目单源直接采购结果公告",
            "http://www.dlztb.com/zbgg/202604/57149.html",
            "04-13",
        )
    ]


def test_parse_category_links_supports_kaifeng_side_navigation() -> None:
    html = """
    <div class="n_left">
      <div class="n_list">
        <dl>
          <dt><a href="/jsgc/index.jhtml">建设工程</a></dt>
          <dd><a href="/jsgcsg/index.jhtml">施工公告</a></dd>
        </dl>
        <ul>
          <li><a href="/zfcg/index.jhtml">政府采购</a></li>
        </ul>
      </div>
    </div>
    """
    urls = parse_category_links(html, base_url="http://www.kfsggzyjyw.cn/")
    assert "http://www.kfsggzyjyw.cn/jsgc/index.jhtml" in urls
    assert "http://www.kfsggzyjyw.cn/jsgcsg/index.jhtml" in urls
    assert "http://www.kfsggzyjyw.cn/zfcg/index.jhtml" in urls


def test_parse_category_links_supports_zmzb_navigation() -> None:
    html = """
    <ul class="subMenu">
      <li><a href="/cms/channel/ywgg1gc/index.htm">工程</a></li>
    </ul>
    <div class="infolist-tab">
      <a href="/cms/channel/ywgg6hw/index.htm">货物</a>
    </div>
    <div class="sideMenu2">
      <div class="sm-list"><a href="/cms/channel/ywgg5fw/index.htm">服务</a></div>
    </div>
    """
    urls = parse_category_links(html, base_url="http://www.zmzb.com/")
    assert "http://www.zmzb.com/cms/channel/ywgg1gc/index.htm" in urls
    assert "http://www.zmzb.com/cms/channel/ywgg6hw/index.htm" in urls
    assert "http://www.zmzb.com/cms/channel/ywgg5fw/index.htm" in urls


def test_parse_next_page_url_supports_txtcenter_next_page() -> None:
    html = """
    <div class="TxtCenter">
      <a href="/jsgcsg/index_2.jhtml">下一页</a>
    </div>
    """
    next_url = parse_next_page_url(
        html, current_url="http://www.kfsggzyjyw.cn/jsgcsg/index.jhtml"
    )
    assert next_url == "http://www.kfsggzyjyw.cn/jsgcsg/index_2.jhtml"


def test_parse_next_page_url_supports_zmzb_js_pagination() -> None:
    html = """
    <div class="pagination">
      <a class="pageItem" href="javascript:;" page="2">下页</a>
    </div>
    """
    next_url = parse_next_page_url(
        html, current_url="http://www.zmzb.com/cms/channel/ywgg1gc/index.htm"
    )
    assert next_url == "http://www.zmzb.com/cms/channel/ywgg1gc/index.htm?pageNo=2"


def test_parse_dlztb_list_page_handles_text_date() -> None:
    html = """
    <div class="item">
      <a href="http://www.dlztb.com/xmxx/202604/178353.html">龙源催化剂江苏有限公司承揽2026年上半年脱硝催化剂供货业务主要生产原料高纯三氧化钼采购公开招标项目招标公告</a>
      <span>04-13</span>
    </div>
    """
    items = parse_dlztb_list_page(html, current_url="http://www.dlztb.com/xmxx/")
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "龙源催化剂江苏有限公司承揽2026年上半年脱硝催化剂供货业务主要生产原料高纯三氧化钼采购公开招标项目招标公告",
            "http://www.dlztb.com/xmxx/202604/178353.html",
            "04-13",
        )
    ]


def test_parse_dlztb_list_page_supports_zbdl() -> None:
    html = """
    <div class="item">
      <a href="http://www.dlztb.com/zbdl/202503/27/55.html">中骏国际招标有限公司</a>
      <span>03-27</span>
    </div>
    """
    items = parse_dlztb_list_page(html, current_url="http://www.dlztb.com/zbdl/")
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "中骏国际招标有限公司",
            "http://www.dlztb.com/zbdl/202503/27/55.html",
            "03-27",
        )
    ]


def test_parse_jszhaobiao_search_page() -> None:
    html = """
    <div class="item">
      <a href="/notice-detail-294909890.html">湖南 湖南博物院（湖南省文物鉴定中心）新风系统改造项目[HNZT-2024-12980]-磋商公告</a>
      <span>04-13</span>
    </div>
    """
    items = parse_jszhaobiao_search_page(
        html, current_url="https://www.jszhaobiao.com/search.html"
    )
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "湖南 湖南博物院（湖南省文物鉴定中心）新风系统改造项目[HNZT-2024-12980]-磋商公告",
            "https://www.jszhaobiao.com/notice-detail-294909890.html",
            "04-13",
        )
    ]


def test_parse_chinabidding_cn_list_page() -> None:
    html = """
    <div class="plist smallw">
      <a href="/zbxx/zbgg/">招标公告</a>
      <a href="/zbgg/U-vztLrEj.html">新疆农科院作物所粮食作物抗逆课题化肥竞价4竞价...</a>
      <span>2026-04-13</span>
    </div>
    """
    items = parse_chinabidding_cn_list_page(
        html, current_url="https://www.chinabidding.cn/zbxx/"
    )
    assert [(it.title, it.link, it.date_raw) for it in items] == [
        (
            "新疆农科院作物所粮食作物抗逆课题化肥竞价4竞价...",
            "https://www.chinabidding.cn/zbgg/U-vztLrEj.html",
            "2026-04-13",
        )
    ]
