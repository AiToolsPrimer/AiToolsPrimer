"""The scout: finds new free platforms worth a presence and prepares everything a human
needs to sign up in two minutes. It never creates the account itself."""
from __future__ import annotations

import html
import re
from typing import Any, Callable
from urllib.parse import unquote, urlsplit, parse_qs

from agency.agents.base import Agent
from agency.safety.payment_guard import GuardedHTTP
from agency.safety.policy import Action, ActionKind, Decision

QUERIES = [
    "free platforms to publish articles 2026 for writers API",
    "new social network 2026 open signup creators",
    "best places to share tech guides community forum",
    "video sharing platforms besides YouTube open API upload",
    "newsletter and blogging platforms free API",
    "podcast and audio platforms free upload API",
    "decentralized social networks fediverse join",
]

KNOWN = {"bluesky", "mastodon", "x", "youtube", "reddit", "telegram", "facebook", "instagram", "threads", "linkedin", "tiktok", "pinterest", "wordpress", "devto", "hashnode", "tumblr", "medium"}


class Scout(Agent):
    role = "platform scout"
    temperature = 0.4

    def __init__(self, llm, store, brand, http: GuardedHTTP, submit: Callable[[Action, dict[str, Any]], Decision], image_agent=None):
        super().__init__(llm, store, brand)
        self.http, self.submit, self.image_agent = http, submit, image_agent

    def search(self, query: str, limit: int = 15) -> list[dict[str, str]]:
        """DuckDuckGo's HTML endpoint: no key, no cost."""
        try:
            r = self.http.get("https://html.duckduckgo.com/html/", params={"q": query})
        except Exception:  # noqa: BLE001
            return []
        out: list[dict[str, str]] = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            if "uddg=" in href:
                href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
            out.append({"url": href, "title": html.unescape(title).strip()})
            if len(out) >= limit:
                break
        return out

    def run(self, max_new: int = 10) -> list[dict[str, Any]]:
        decision = self.submit(Action(ActionKind.SCOUT_SEARCH, "web"), {})
        if not decision.allowed:
            return [{"skipped": decision.reason}]
        raw: list[dict[str, str]] = []
        for q in QUERIES:
            raw.extend(self.search(q))
        seen, candidates = set(), []
        for r in raw:
            host = (urlsplit(r["url"]).hostname or "").lower()
            if not host or host in seen:
                continue
            seen.add(host)
            candidates.append(r)
        if not candidates:
            return []
        known = sorted(KNOWN | {h.lower() for h in self.brand.handles})
        data = self.ask_json(
            "From these search results, identify platforms (not articles) where a brand like ours could publish or hold a profile for free. "
            f"Skip anything we already use: {known}. Skip paid-only services, ad networks and anything that requires a credit card.\n"
            f"Results: {candidates[:60]}\n"
            'Return JSON: {"platforms": [{"name": "...", "url": "https://...", "kind": "social|blog|video|forum|newsletter|podcast|directory", '
            '"free": true, "has_api": true, "fit_score": 0.0-1.0, "rationale": "one sentence"}]}'
        )
        added = []
        for p in (data.get("platforms", []) if isinstance(data, dict) else [])[:max_new]:
            if not p.get("url"):
                continue
            sid = self.store.add_scout(p.get("name", p["url"]), p["url"], p.get("kind", ""), p.get("free"), p.get("has_api"), float(p.get("fit_score", 0)), p.get("rationale", ""))
            if sid:
                added.append({"id": sid, **p})
        return added

    def prepare_kit(self, scout_id: int) -> dict[str, Any] | None:
        rows = [r for r in self.store.list_scout() if r["id"] == scout_id]
        if not rows:
            return None
        row = rows[0]
        decision = self.submit(Action(ActionKind.SIGNUP_KIT, row["name"]), {})
        if not decision.allowed:
            return {"skipped": decision.reason}
        kit = self.ask_json(
            f"Prepare a sign-up kit for {row['name']} ({row['url']}), a {row['kind']} platform.\n"
            f"Our handles elsewhere: {self.brand.handles}\n"
            'Return JSON: {"handle": "...", "display_name": "...", "short_bio": "max 160 chars", "long_bio": "2-3 sentences", "website": "...", '
            '"avatar_prompt": "visual brief", "banner_prompt": "visual brief", "first_posts": ["...", "...", "..."], "steps": ["human step 1", "..."]}'
        )
        if self.image_agent:
            try:
                kit["avatar_asset"] = self.image_agent.make(kit.get("avatar_prompt", "minimal monogram logo"), size="square", topic=f"avatar {row['name']}")
                kit["banner_asset"] = self.image_agent.make(kit.get("banner_prompt", "abstract banner"), size="og", topic=f"banner {row['name']}")
            except Exception as e:  # noqa: BLE001
                kit["asset_error"] = str(e)[:200]
        self.store.set_scout_kit(scout_id, kit)
        return kit
