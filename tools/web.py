"""Web tools: internet search and URL fetching (no API key required)."""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel, Field

from .base import register


class WebSearchInput(BaseModel):
    query: str = Field(..., description="检索关键词，最多 5 个关键词，用空格分隔")
    max_results: int = Field(5, description="返回结果数量上限，1-10")


class WebFetchInput(BaseModel):
    url: str = Field(..., description="要抓取的网页 URL")
    max_chars: int = Field(4000, description="返回正文的最大字符数")


def web_search(query: str, max_results: int = 5) -> str:
    """Best-effort internet search without an API key."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # legacy package name
        except ImportError:
            return "需要安装依赖：pip install ddgs"

    max_results = max(1, min(10, int(max_results)))
    try:
        results: list[dict[str, Any]] = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": item.get("title", ""),
                    "href": item.get("href", ""),
                    "body": item.get("body", ""),
                })
        if not results:
            return "未检索到结果。"
        return __import__("json").dumps(results, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001 - network / rate-limit etc.
        return f"web_search 失败：{exc}"


def web_fetch(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return readable text (best-effort)."""
    max_chars = max(200, min(20000, int(max_chars)))
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MetamorphAgent/0.1)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(2_000_000).decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        return f"web_fetch 失败：{exc}"
    return _html_to_text(raw)[:max_chars]


def _html_to_text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(br|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


register("web_search", WebSearchInput, web_search)
register("web_fetch", WebFetchInput, web_fetch)
