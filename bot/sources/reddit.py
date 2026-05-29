import feedparser
import requests
from datetime import datetime
from typing import Optional

SUBREDDITS = [
    "investing",
    "wallstreetbets",
    "stocks",
    "SecurityAnalysis",
    "finance",
    "economics",
    "options",
    "StockMarket",
]

HEADERS = {"User-Agent": "andiamo-finance-bot/1.0"}


def fetch_subreddit_posts(subreddit: str, limit: int = 25, sort: str = "hot") -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        posts = []
        for child in data["data"]["children"]:
            p = child["data"]
            posts.append({
                "title": p.get("title", ""),
                "score": p.get("score", 0),
                "url": f"https://reddit.com{p.get('permalink', '')}",
                "selftext": p.get("selftext", "")[:1000],
                "created_utc": datetime.utcfromtimestamp(p.get("created_utc", 0)).isoformat(),
                "num_comments": p.get("num_comments", 0),
                "subreddit": subreddit,
                "flair": p.get("link_flair_text", ""),
            })
        return posts
    except Exception as e:
        return [{"error": str(e), "subreddit": subreddit}]


def search_reddit(query: str, subreddits: Optional[list[str]] = None, limit: int = 15) -> list[dict]:
    targets = subreddits or SUBREDDITS
    results = []
    for sub in targets:
        url = f"https://www.reddit.com/r/{sub}/search.json?q={requests.utils.quote(query)}&restrict_sr=1&sort=relevance&limit={limit}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            for child in data["data"]["children"]:
                p = child["data"]
                results.append({
                    "title": p.get("title", ""),
                    "score": p.get("score", 0),
                    "url": f"https://reddit.com{p.get('permalink', '')}",
                    "selftext": p.get("selftext", "")[:1200],
                    "created_utc": datetime.utcfromtimestamp(p.get("created_utc", 0)).isoformat(),
                    "subreddit": sub,
                })
        except Exception:
            continue
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results[:limit * 2]


def fetch_subreddit_rss(subreddit: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/hot.rss"
    try:
        feed = feedparser.parse(url)
        posts = []
        for entry in feed.entries[:20]:
            posts.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:800],
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "subreddit": subreddit,
            })
        return posts
    except Exception as e:
        return [{"error": str(e), "subreddit": subreddit}]


def get_top_finance_posts(limit_per_sub: int = 10) -> list[dict]:
    all_posts = []
    for sub in SUBREDDITS[:5]:
        posts = fetch_subreddit_posts(sub, limit=limit_per_sub)
        all_posts.extend(posts)
    all_posts.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_posts
