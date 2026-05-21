from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from bs4 import BeautifulSoup
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


@dataclass(frozen=True)
class ListItem:
    title: str
    link: str
    date_raw: str


@dataclass(frozen=True)
class SiteEntry:
    name: str
    url: str


def parse_list_page(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    for li in soup.select(".list li"):
        a = li.select_one("a")
        span = li.select_one("span")
        if not a or not span:
            continue
        title = a.get_text(strip=True)
        link = str(a.get("href") or "").strip()
        date_raw = span.get_text(strip=True)
        if not title or not link:
            continue
        items.append(ListItem(title=title, link=link, date_raw=date_raw))
    return items


_RE_PUBLISHED_DATE = re.compile(r"发布时间[:：]\s*(\d{4}-\d{2}-\d{2})")


def parse_notice_list_page(html: str) -> list[ListItem]:
    """Parse newer list pages where date is embedded as text like: 发布时间：YYYY-MM-DD HH:MM:SS"""

    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []

    for li in soup.find_all("li"):
        text = li.get_text(" ", strip=True)
        m = _RE_PUBLISHED_DATE.search(text)
        if not m:
            continue
        a = li.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        link = str(a.get("href") or "").strip()
        if not title or not link:
            continue
        items.append(ListItem(title=title, link=link, date_raw=m.group(1)))

    return items


def parse_zcpt_list_page(html: str) -> list[ListItem]:
    """Parse zcpt.zgpmsm.com.cn list pages.

    Items are in li.wb-data-list; title is in a[href], date in span.wb-data-date (YYYY-MM-DD).
    """

    soup = BeautifulSoup(html, "lxml")
    out: list[ListItem] = []
    for li in soup.select("li.wb-data-list"):
        a = li.select_one("a[href]")
        d = li.select_one("span.wb-data-date")
        if not a or not d:
            continue
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        date_raw = d.get_text(strip=True)
        if not title or not href or not date_raw:
            continue
        out.append(ListItem(title=title, link=href, date_raw=date_raw))
    return out


def parse_category_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    selector = ", ".join(
        [
            "ul.list-se a[href]",
            "ul.menu-list a[href]",
            "div.n_left .n_list dl dt a[href]",
            "div.n_left .n_list dl dd a[href]",
            "div.n_left .n_list ul li a[href]",
            "ul.subMenu a[href]",
            ".infolist-tab a[href]",
            ".sideMenu2 .sm-list a[href]",
        ]
    )
    seen: set[str] = set()
    for a in soup.select(selector):
        href = str(a.get("href") or "").strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        if full in seen:
            continue
        seen.add(full)
        urls.append(full)
    return urls


def parse_next_page_url(html: str, current_url: str) -> str | None:
    """Find next page link in pager ("下一页"). Returns absolute URL if found."""

    soup = BeautifulSoup(html, "lxml")
    # Common pager container on this site.
    fenye = soup.select_one("div.fenye")
    txtcenter = soup.select_one("div.TxtCenter")
    pagination = soup.select_one("div.pagination")
    scope = fenye or txtcenter or pagination or soup
    for a in scope.find_all("a"):
        href = str(a.get("href") or "").strip()
        text = a.get_text(" ", strip=True)
        if text not in {"下一页", "下页"} and a.get("aria-label") != "Next":
            continue
        if href and href != "javascript:;":
            return urljoin(current_url, href)
        page = str(a.get("page") or "").strip()
        if page.isdigit():
            parts = urlsplit(current_url)
            qs = dict(parse_qsl(parts.query, keep_blank_values=True))
            qs["pageNo"] = page
            return urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(qs), parts.fragment)
            )
    return None


_RE_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_DATE_TEXT = re.compile(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})")
_RE_DATE_HREF = re.compile(r"20\d{2}[01]\d[0-3]\d")


def parse_site_list_markdown(markdown: str) -> list[SiteEntry]:
    entries: list[SiteEntry] = []
    seen: set[tuple[str, str]] = set()
    for line in markdown.splitlines():
        if not line.startswith("| ") or line.startswith("| ---"):
            continue
        parts = line.strip().strip("|").split(" | ")
        if len(parts) != 2:
            continue
        name, links = parts[0].strip(), parts[1].strip()
        if name == "名称":
            continue
        for _, url in _RE_MARKDOWN_LINK.findall(links):
            key = (name, url)
            if key in seen:
                continue
            seen.add(key)
            entries.append(SiteEntry(name=name, url=url))
    return entries


def parse_generic_list_page(html: str, current_url: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()

    for a in soup.select("a[href]"):
        href = str(a.get("href") or "").strip()
        title = a.get_text(" ", strip=True)
        if not href or not title or href.startswith(("javascript:", "#", "mailto:")):
            continue

        context = a.get_text(" ", strip=True)
        parent = a.parent
        if parent is not None:
            context = parent.get_text(" ", strip=True)
        m = _RE_DATE_TEXT.search(context)
        if not m:
            continue

        date_raw = m.group(1).replace("年", "-").replace("月", "-").replace("日", "")
        date_raw = date_raw.replace("/", "-").replace(".", "-")
        link = urljoin(current_url, href)
        key = (title, link)
        if key in seen:
            continue
        seen.add(key)
        items.append(ListItem(title=title, link=link, date_raw=date_raw))

    return items


def parse_ccgp_list_page(html: str, current_url: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()

    for li in soup.select("li"):
        a = li.select_one("a[href]")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        if not title or not href:
            continue
        text = li.get_text(" ", strip=True)
        m = _RE_DATE_TEXT.search(text)
        link = urljoin(current_url, href)
        if m:
            date_raw = (
                m.group(1)
                .replace("年", "-")
                .replace("月", "-")
                .replace("日", "")
                .replace("/", "-")
                .replace(".", "-")
            )
        else:
            href_date = _RE_DATE_HREF.search(href)
            if not href_date:
                continue
            raw = href_date.group(0)
            date_raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        key = (title, link)
        if key in seen:
            continue
        seen.add(key)
        items.append(ListItem(title=title, link=link, date_raw=date_raw))

    return items


def parse_henan_notice_page(html: str, current_url: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()

    for a in soup.select("a[href*='/jyxx/'][href$='.html']"):
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        if not title or not href:
            continue

        parent_text = a.parent.get_text(" ", strip=True) if a.parent else title
        m = _RE_DATE_TEXT.search(parent_text)
        if not m:
            m = _RE_DATE_HREF.search(href)
            if not m:
                continue
            raw = m.group(0)
            date_raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        else:
            date_raw = (
                m.group(1)
                .replace("年", "-")
                .replace("月", "-")
                .replace("日", "")
                .replace("/", "-")
                .replace(".", "-")
            )

        link = urljoin(current_url, href)
        key = (title, link)
        if key in seen:
            continue
        seen.add(key)
        items.append(ListItem(title=title, link=link, date_raw=date_raw))

    return items


def parse_cuecp_api_payload(payload_text: str, current_url: str) -> list[ListItem]:
    payload = json.loads(payload_text)
    data = payload.get("data")
    groups: list[list[dict]] = []
    if isinstance(data, list):
        groups.append(data)
    elif isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                groups.append(value)

    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for row in group:
            title = str(row.get("noticeTitle") or "").strip()
            notice_id = str(row.get("id") or "").strip()
            if not title or not notice_id:
                continue
            date_raw = _cuecp_notice_date(row)
            if not date_raw:
                continue
            link = urljoin(current_url, f"#/notice/{notice_id}")
            key = (title, link)
            if key in seen:
                continue
            seen.add(key)
            items.append(ListItem(title=title, link=link, date_raw=date_raw))

    return items


def parse_powerec_content_api_payload(
    payload_text: str, current_url: str
) -> list[ListItem]:
    payload = json.loads(payload_text)
    res = payload.get("res") or {}
    rows = res.get("rows") or []
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        title = str(row.get("title") or "").strip()
        href = str(row.get("url") or "").strip()
        raw_date = str(row.get("publishDate") or "").strip()
        if not title or not href or not raw_date:
            continue
        m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", raw_date)
        if not m:
            continue
        date_raw = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        link = urljoin(current_url, href)
        key = (title, link)
        if key in seen:
            continue
        seen.add(key)
        items.append(ListItem(title=title, link=link, date_raw=date_raw))
    return items


def parse_qianlima_list_page(html: str, current_url: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()
    for row in soup.select(".list-single"):
        a = row.select_one("a.title[href]")
        d = row.select_one(".time-block")
        if not a or not d:
            continue
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        date_raw = d.get_text(" ", strip=True)
        if not title or not href or not date_raw:
            continue
        key = (title, href)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            ListItem(title=title, link=urljoin(current_url, href), date_raw=date_raw)
        )
    return items


def parse_chinabidding_cn_homepage(html: str, current_url: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()
    for row in soup.select(".notice-item"):
        a = row.select_one("a[href]")
        d = row.select_one(".item-right")
        if not a or not d:
            continue
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        date_raw = d.get_text(" ", strip=True)
        if not title or not href or not date_raw:
            continue
        key = (title, href)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            ListItem(title=title, link=urljoin(current_url, href), date_raw=date_raw)
        )
    return items


def parse_jszhaobiao_search_page(html: str, current_url: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()
    for a in soup.select("a[href*='notice-detail-'], a[href*='search.html?btns=']"):
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        if not title or not href:
            continue
        parent = a.parent.get_text(" ", strip=True) if a.parent else title
        short_matches = re.findall(r"(?<!\d)(\d{2}[-/.]\d{2})(?!\d)", parent)
        if short_matches:
            date_raw = short_matches[-1].replace("/", "-").replace(".", "-")
        else:
            m = _RE_DATE_TEXT.search(parent)
            if not m:
                continue
            date_raw = (
                m.group(1).replace("年", "-").replace("月", "-").replace("日", "")
            )
            date_raw = date_raw.replace("/", "-").replace(".", "-")
        key = (title, href)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            ListItem(title=title, link=urljoin(current_url, href), date_raw=date_raw)
        )
    return items


def parse_dlztb_list_page(html: str, current_url: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()
    for a in soup.select(
        'a[href*="/zbgg/"], a[href*="/xmxx/"], a[href*="/news/"], a[href*="/buy/"], a[href*="/zbdl/"], a[href*="/quote/"]'
    ):
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        if not title or not href:
            continue
        parent = a.parent.get_text(" ", strip=True) if a.parent else title
        short = re.search(r"(?<!\d)(\d{2}[-/.]\d{2})(?!\d)", parent)
        if short:
            date_raw = short.group(1).replace("/", "-").replace(".", "-")
        else:
            m = _RE_DATE_TEXT.search(parent)
            if not m:
                continue
            date_raw = (
                m.group(1).replace("年", "-").replace("月", "-").replace("日", "")
            )
            date_raw = date_raw.replace("/", "-").replace(".", "-")
        link = urljoin(current_url, href)
        key = (title, link)
        if key in seen:
            continue
        seen.add(key)
        items.append(ListItem(title=title, link=link, date_raw=date_raw))
    return items


def parse_chinabidding_cn_list_page(html: str, current_url: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    seen: set[tuple[str, str]] = set()
    for a in soup.select(
        "a[href*='/zbgg/'], a[href*='/cgxx/'], a[href*='/zbgs/'], a[href*='/xmxx/']"
    ):
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        if not title or not href or href.startswith("javascript:"):
            continue
        if ".html" not in href:
            continue
        container = a.parent if a.parent is not None else a
        text = container.get_text(" ", strip=True)
        long_matches = re.findall(r"(20\d{2}-\d{2}-\d{2})", text)
        if long_matches:
            date_raw = long_matches[-1]
        else:
            short_matches = re.findall(r"(?<!\d)(\d{2}[-/.]\d{2})(?!\d)", text)
            if not short_matches:
                continue
            date_raw = short_matches[-1].replace("/", "-").replace(".", "-")
        link = urljoin(current_url, href)
        key = (title, link)
        if key in seen:
            continue
        seen.add(key)
        items.append(ListItem(title=title, link=link, date_raw=date_raw))
    return items


def _cuecp_notice_date(row: dict) -> str | None:
    for key in ("startTime", "createDate", "modifyDate", "endTime"):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        raw = raw.replace("T", " ")
        m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", raw)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        try:
            return datetime.fromisoformat(raw).date().isoformat()
        except ValueError:
            continue
    return None


def extract_detail_content(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    selectors = [
        ".article-content",
        "div.article-content",
        ".ewb-article",
        "div.ewb-article",
        ".Content",
        "div.Content",
        "#content",
        "div#content",
        ".content",
        "div.content",
    ]
    for sel in selectors:
        node = soup.select_one(sel)
        if not node:
            continue
        text = node.get_text("\n", strip=True)
        if text:
            return text

    # Heuristic fallback: pick the largest div that contains publish marker.
    best_text = ""
    for div in soup.find_all("div"):
        t = div.get_text("\n", strip=True)
        if not t:
            continue
        if "发布时间" not in t:
            continue
        if len(t) > len(best_text):
            best_text = t
    return best_text
