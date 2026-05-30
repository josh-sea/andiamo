import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from typing import Optional
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; andiamo-finance-bot/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}


def ddg_search(query: str, max_results: int = 10, time_filter: Optional[str] = None) -> list[dict]:
    """DuckDuckGo web search. time_filter: 'd' day, 'w' week, 'm' month, 'y' year."""
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results, timelimit=time_filter):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
    except Exception as e:
        results.append({"error": str(e)})
    return results


def ddg_news(query: str, max_results: int = 15, time_filter: Optional[str] = None) -> list[dict]:
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results, timelimit=time_filter):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("body", ""),
                    "source": r.get("source", ""),
                    "date": r.get("date", ""),
                })
    except Exception as e:
        results.append({"error": str(e)})
    return results


def fetch_page_text(url: str, max_chars: int = 8000) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l for l in text.splitlines() if len(l.strip()) > 30]
        return "\n".join(lines)[:max_chars]
    except Exception as e:
        return f"[fetch error: {e}]"


def search_and_fetch(query: str, n_results: int = 5, fetch_top: int = 3) -> list[dict]:
    results = ddg_search(query, max_results=n_results)
    enriched = []
    for i, r in enumerate(results):
        if "error" in r:
            enriched.append(r)
            continue
        item = dict(r)
        if i < fetch_top and r.get("url"):
            time.sleep(0.5)
            item["full_text"] = fetch_page_text(r["url"])
        enriched.append(item)
    return enriched
