"""The analyst: pulls metrics for what we published and turns them into lessons."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from agency.agents.base import Agent
from agency.platforms.base import Platform
from agency.safety.policy import Action, ActionKind, Decision


class Analyst(Agent):
    role = "growth analyst"
    desk = "analyst"
    temperature = 0.3

    def __init__(self, llm, store, brand, platforms: dict[str, Platform], submit: Callable[[Action, dict[str, Any]], Decision]):
        super().__init__(llm, store, brand)
        self.platforms, self.submit = platforms, submit

    def collect(self, days: int = 30) -> int:
        with self.report("collecting metrics"):
            return self._collect(days)

    def _collect(self, days: int = 30) -> int:
        n = 0
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        for row in self.store.list_content(status="published", limit=500):
            if (row.get("published_at") or "") < since or not row.get("remote_id"):
                continue
            p = self.platforms.get(row["platform"])
            if not p:
                continue
            if not self.submit(Action(ActionKind.READ_METRICS, p.name), {}).allowed:
                return n
            m = p.fetch_metrics(row["remote_id"])
            if any(v is not None for v in (m.impressions, m.likes, m.replies, m.shares, m.clicks, m.followers)):
                self.store.add_metrics(p.name, row["id"], row["remote_id"], impressions=m.impressions, likes=m.likes, replies=m.replies, shares=m.shares, clicks=m.clicks, followers=m.followers, raw=m.raw)
                n += 1
        return n

    def lessons(self) -> str:
        with self.report("writing the lessons of the last 14 days"):
            return self._report()

    def _report(self) -> str:
        summary = self.store.metrics_summary(14)
        if not summary:
            return "No metrics yet."
        data = self.ask_json(
            f"Here are the last 14 days of results per post (max values): {summary}\n"
            "Write what worked and what did not: topics, formats, platforms, posting times if visible. Then give three concrete instructions for the next week. "
            'Return JSON: {"insights": ["..."], "instructions": ["..."]}'
        )
        text = "Insights: " + " | ".join(data.get("insights", [])) + "\nNext week: " + " | ".join(data.get("instructions", []))
        self.store.add_note("analyst", text)
        return text
