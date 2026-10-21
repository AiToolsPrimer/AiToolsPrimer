"""Weekly platform news watch: for every card, look for rule or algorithm changes since the
last check, and turn findings into update proposals a human approves from the dashboard."""
from __future__ import annotations

import datetime as dt
import html
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from agency.agents.base import Agent
from agency.knowledge.base import KnowledgeBase
from agency.safety.payment_guard import GuardedHTTP

QUERY = "{label} algorithm change OR new rule OR policy update OR new limit {month} {year}"


class NewsWatch(Agent):
    role = "platform policy analyst"
    temperature = 0.2

    def __init__(self, llm, store, brand, http: GuardedHTTP, kb: KnowledgeBase):
        super().__init__(llm, store, brand)
        self.http, self.kb = http, kb

    def search(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        try:
            r = self.http.get("https://html.duckduckgo.com/html/", params={"q": query})
        except Exception:  # noqa: BLE001
            return []
        out: list[dict[str, str]] = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(?:.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>)?', r.text, re.S):
            href, title, snippet = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)), re.sub(r"<[^>]+>", "", m.group(3) or "")
            if "uddg=" in href:
                href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
            out.append({"url": href, "title": html.unescape(title).strip(), "snippet": html.unescape(snippet).strip()})
            if len(out) >= limit:
                break
        return out

    def check_card(self, key: str) -> list[dict[str, Any]]:
        card = self.kb.card(key)
        if not card:
            return []
        now = dt.date.today()
        results = self.search(QUERY.format(label=card.label, month=now.strftime("%B"), year=now.year))
        if not results:
            return []
        data = self.ask_json(
            f"Our knowledge card for {card.label} (last checked {card.meta.get('last_checked')}):\n{card.body[:5000]}\n\n"
            f"Fresh search results:\n{results}\n\n"
            "List only changes that would alter what we do (limits, labels, link handling, formats, enforcement, algorithm signals). "
            "Ignore marketing fluff and anything already on the card. Each item needs the source URL.\n"
            'Return JSON: {"changes": [{"summary": "one sentence", "field": "char_limit|hashtags_max|link_policy|ai_label|cadence|algorithm|rules|none", "new_value": "...", "source": "https://...", "confidence": 0.0-1.0}]}'
        )
        changes = data.get("changes", []) if isinstance(data, dict) else []
        out = []
        for ch in changes:
            if not ch.get("summary"):
                continue
            pid = self.store.add_knowledge_update(key, ch["summary"], ch.get("field", "none"), str(ch.get("new_value", "")), ch.get("source", ""), float(ch.get("confidence", 0.5)))
            if pid:
                out.append({"id": pid, **ch})
        return out

    def run(self, max_cards: int | None = None) -> dict[str, Any]:
        keys = list(self.kb.cards)
        if max_cards:
            keys = keys[:max_cards]
        found = {k: self.check_card(k) for k in keys}
        for k in keys:
            if not found[k]:
                self.store.touch_knowledge_check(k)
        return {k: len(v) for k, v in found.items()}

    def apply(self, update_id: int) -> None:
        u = self.store.get_knowledge_update(update_id)
        if not u:
            return
        self.kb.apply_update(u["platform"], f"{u['summary']}" + (f" → {u['field']} = {u['new_value']}" if u.get("field") not in (None, "", "none") else ""), source=u.get("source", ""))
        if u.get("field") in ("char_limit", "hashtags_max", "link_policy", "ai_label") and u.get("new_value"):
            self.kb.set_meta(u["platform"], u["field"], u["new_value"])
        self.store.set_knowledge_update_status(update_id, "applied")
