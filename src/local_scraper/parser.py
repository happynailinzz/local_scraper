from __future__ import annotations

from dataclasses import dataclass
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin


@dataclass(frozen=True)
class ListItem:
    title: str
    link: str
    date_raw: str


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
    for a in soup.select("ul.list-se a[href], ul.menu-list a[href]"):
        href = str(a.get("href") or "").strip()
        if not href:
            continue
        urls.append(urljoin(base_url, href))
    return urls


def parse_next_page_url(html: str, current_url: str) -> str | None:
    """Find next page link in pager ("下一页"). Returns absolute URL if found."""

    soup = BeautifulSoup(html, "lxml")
    # Common pager container on this site.
    fenye = soup.select_one("div.fenye")
    scope = fenye if fenye is not None else soup
    for a in scope.find_all("a"):
        if a.get_text(strip=True) != "下一页":
            continue
        href = str(a.get("href") or "").strip()
        if not href:
            return None
        return urljoin(current_url, href)
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
