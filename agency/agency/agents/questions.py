"""Community questions: real questions on Reddit, Hacker News, Stack Exchange and Quora
that one of our guides answers.  Reddit and Quora get a draft to rewrite in your words;
Hacker News and Stack Exchange get a fact card only, because their rules forbid AI text."""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from agency.agents.base import Agent
from agency.safety.payment_guard import GuardedHTTP

FACT_CARD_ONLY = {"hackernews", "stackexchange"}


class QuestionsAgent(Agent):
    role = "community questions"
    desk = "community"
    temperature = 0.4

    def __init__(self, llm, store, brand, http: GuardedHTTP, factcheck=None):
        super().__init__(llm, store, brand)
        self.http, self.factcheck = http, factcheck

    def reddit(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        try:
            r = self.http.get("https://www.reddit.com/search.json", params={"q": query, "sort": "new", "limit": limit, "t": "month"}, headers={"Accept": "application/json"})
            if r.status_code != 200:
                return []
            return [{"platform": "reddit", "url": "https://www.reddit.com" + d["data"]["permalink"], "title": d["data"].get("title", ""), "text": d["data"].get("selftext", "")[:1500], "sub": d["data"].get("subreddit", "")} for d in r.json().get("data", {}).get("children", [])]
        except Exception:  # noqa: BLE001
            return []

    def hackernews(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        try:
            r = self.http.get("https://hn.algolia.com/api/v1/search_by_date", params={"query": query, "tags": "ask_hn", "hitsPerPage": limit})
            if r.status_code != 200:
                return []
            return [{"platform": "hackernews", "url": f"https://news.ycombinator.com/item?id={h.get('objectID')}", "title": h.get("title", ""), "text": (h.get("story_text") or "")[:1500]} for h in r.json().get("hits", [])]
        except Exception:  # noqa: BLE001
            return []

    def stackexchange(self, query: str, site: str = "superuser", limit: int = 10) -> list[dict[str, Any]]:
        try:
            r = self.http.get("https://api.stackexchange.com/2.3/search/advanced", params={"q": query, "site": site, "order": "desc", "sort": "creation", "accepted": "False", "pagesize": limit})
            if r.status_code != 200:
                return []
            return [{"platform": "stackexchange", "url": q.get("link", ""), "title": html.unescape(q.get("title", "")), "text": ""} for q in r.json().get("items", [])]
        except Exception:  # noqa: BLE001
            return []

    def quora(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        try:
            r = self.http.get("https://html.duckduckgo.com/html/", params={"q": f"site:quora.com {query}"})
        except Exception:  # noqa: BLE001
            return []
        out = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            if "uddg=" in href:
                href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
            if "quora.com" in href:
                out.append({"platform": "quora", "url": href, "title": html.unescape(title).strip(), "text": ""})
            if len(out) >= limit:
                break
        return out

    def run(self, guides: list[dict[str, str]], max_per_source: int = 6) -> list[dict[str, Any]]:
        queries = [p for p in self.brand.pillars][:4]
        found: list[dict[str, Any]] = []
        with self.report("looking for questions our guides answer", steps=len(queries)):
            for i, q in enumerate(queries, 1):
                self.progress(q[:50], i, len(queries))
                found += self.reddit(q, max_per_source) + self.hackernews(q, max_per_source) + self.stackexchange(q, limit=max_per_source) + self.quora(q, max_per_source)
            new = [f for f in found if f.get("url") and self.store.question_is_new(f["url"])]
            if not new:
                return []
            data = self.ask_json(
                f"Questions found online: {[{k: v for k, v in f.items() if k in ('platform','url','title','text')} for f in new[:40]]}\nOur guides (url, title): {guides[:80]}\n"
                "Keep only questions that one specific guide genuinely answers. For each: the guide URL, a fit score, and what the guide says that answers it.\n"
                'Return JSON: {"matches": [{"url": "...", "guide_url": "...", "fit": 0.0-1.0, "answer_points": ["..."]}]}'
            )
            out = []
            by_url = {f["url"]: f for f in new}
            for m in (data.get("matches", []) if isinstance(data, dict) else []):
                f = by_url.get(m.get("url"))
                if not f or float(m.get("fit", 0)) < 0.6:
                    continue
                facts = self.factcheck.facts_for(m["guide_url"]) if (self.factcheck and str(m.get("guide_url", "")).startswith("http")) else []
                if f["platform"] in FACT_CARD_ONLY:
                    body = "FACT CARD (write the answer yourself; this platform forbids AI text)\n\n" + "\n".join(f"- {p}" for p in m.get("answer_points", [])) + f"\n\nGuide: {m['guide_url']}\n\nFacts:\n" + self.factcheck.facts_text(facts) if self.factcheck else ""
                    status = "manual"
                else:
                    draft = self.ask_json(
                        f"Draft an answer to this {f['platform']} question for the owner of {self.brand.name} to rewrite in their own words.\nQuestion: {f['title']}\n{f['text'][:1500]}\n"
                        f"Verified facts (only these): {self.factcheck.facts_text(facts) if self.factcheck else ''}\nRules: answer first, disclose that we run the site, link only at the end and only if it adds the full table/test; no hype.\n"
                        'Return JSON: {"text": "..."}'
                    )
                    body = str(draft.get("text", "")).strip()
                    if self.factcheck:
                        r = self.factcheck.verify(body, facts, kind="answer")
                        body = r.text
                    status = "manual"
                cid = self.store.add_content("answer", f["platform"], topic=f["title"][:80], title=f["title"][:200], body=body, status=status, meta={"target_url": f["url"], "guide": m["guide_url"], "manual_mode": "manual", "fit": m.get("fit")})
                self.store.add_question(f["platform"], f["url"], f["title"], m["guide_url"], float(m.get("fit", 0)), cid)
                out.append({"content_id": cid, "url": f["url"], "platform": f["platform"]})
            return out
