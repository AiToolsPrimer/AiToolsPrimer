"""The strategist: reads the site, scans free trend sources, proposes what to make."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from agency.agents.base import Agent
from agency.safety.payment_guard import GuardedHTTP

TREND_SOURCES = [
    ("hacker-news", "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"),
    ("reddit-artificial", "https://www.reddit.com/r/artificial/top.json?t=day&limit=25"),
    ("reddit-technology", "https://www.reddit.com/r/technology/top.json?t=day&limit=25"),
    ("reddit-privacy", "https://www.reddit.com/r/privacy/top.json?t=day&limit=15"),
    ("google-trends-us", "https://trends.google.com/trending/rss?geo=US"),
]


class Strategist(Agent):
    role = "content strategist"
    desk = "strategist"
    temperature = 0.5

    def __init__(self, llm, store, brand, http: GuardedHTTP, indexnow=None, toggles=None):
        super().__init__(llm, store, brand)
        self.http = http
        self.indexnow, self.toggles = indexnow, toggles

    def push_new_urls(self, urls: list[str]) -> int:
        """New site URLs go to IndexNow (Bing and partners) once."""
        if not self.indexnow or (self.toggles is not None and not self.toggles.get("push_indexnow")):
            return 0
        fresh = self.store.new_site_urls(urls)
        if fresh:
            self.indexnow.submit(fresh)
            self.store.mark_site_urls_submitted(fresh)
        return len(fresh)

    # ------------------------------------------------------------------ research
    def site_inventory(self, max_pages: int = 60) -> list[dict[str, str]]:
        """Titles and URLs from the brand site's sitemap (or homepage links)."""
        pages: list[dict[str, str]] = []
        base = self.brand.site.rstrip("/")
        try:
            r = self.http.get(f"{base}/sitemap.xml")
            urls = re.findall(r"<loc>(.*?)</loc>", r.text) if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            urls = []
        if not urls:
            try:
                r = self.http.get(base)
                urls = [urljoin(base, h) for h in re.findall(r'href="([^"#]+)"', r.text) if h.startswith("/") or h.startswith(base)]
            except Exception:  # noqa: BLE001
                urls = []
        seen = set()
        for u in urls:
            if u in seen or len(pages) >= max_pages:
                continue
            seen.add(u)
            title = u.rstrip("/").rsplit("/", 1)[-1].replace("-", " ") or "home"
            pages.append({"url": u, "title": title})
        return pages

    def trends(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for name, url in TREND_SOURCES:
            try:
                r = self.http.get(url, headers={"Accept": "application/json, application/rss+xml;q=0.9, */*;q=0.5"})
                if r.status_code != 200:
                    continue
                if name == "hacker-news":
                    for h in r.json().get("hits", []):
                        items.append({"source": name, "title": h.get("title", ""), "url": h.get("url") or ""})
                elif name.startswith("reddit"):
                    for c in r.json().get("data", {}).get("children", []):
                        d = c.get("data", {})
                        items.append({"source": name, "title": d.get("title", ""), "url": d.get("url", "")})
                else:
                    for t in re.findall(r"<title>(.*?)</title>", r.text)[1:]:
                        items.append({"source": name, "title": re.sub(r"<!\[CDATA\[|\]\]>", "", t)})
            except Exception:  # noqa: BLE001
                continue
        return items[:120]

    # ------------------------------------------------------------------ thinking
    def opportunities(self, max_items: int = 8) -> list[dict[str, Any]]:
        with self.report("research: site inventory, trends, opportunities", steps=3):
            self.progress("reading the site", 1, 3)
            pages = self.site_inventory()
            self.push_new_urls([p["url"] for p in pages])
            self.progress("scanning trends", 2, 3)
            trends = self.trends()
            self.progress("proposing opportunities", 3, 3)
            return self._opportunities(pages, trends, max_items)

    def _opportunities(self, pages, trends, max_items: int = 8) -> list[dict[str, Any]]:
        recent = self.store.recent_topics(30)
        notes = "\n".join(f"- {n['text'][:300]}" for n in self.store.recent_notes(8))
        data = self.ask_json(
            "Propose the most promising content opportunities for the next 24-48 hours.\n"
            f"Our existing guides (URL and slug): {pages[:60]}\n"
            f"What is trending today (titles): {[t['title'] for t in trends][:100]}\n"
            f"Topics we covered in the last 30 days (avoid repeating): {recent}\n"
            f"Analyst notes about what worked: {notes or '(none yet)'}\n"
            "Pick angles where a trending topic meets one of our guides or pillars, where plain-English verification is the value, "
            "and where a reader has a real question. Every opportunity should name the guide URL it should link to (an existing one, or 'new' if we need to write it).\n"
            f'Return JSON: {{"opportunities": [{{"topic": "...", "angle": "...", "why_now": "...", "guide_url": "...", "formats": ["post","article","video"], "platforms": ["bluesky","youtube"], "keywords": ["..."], "priority": 1}}]}} with at most {max_items} items, priority 1 = best.',
        )
        opps = data.get("opportunities", []) if isinstance(data, dict) else []
        return sorted(opps, key=lambda o: o.get("priority", 99))[:max_items]
