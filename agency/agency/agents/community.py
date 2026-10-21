"""Community manager: reads comments under our own posts and answers them (or queues the answer)."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from agency.agents.base import Agent
from agency.agents.writer import Writer
from agency.platforms.base import Comment, Platform
from agency.safety.policy import Action, ActionKind, Decision


class CommunityManager(Agent):
    role = "community manager"

    def __init__(self, llm, store, brand, writer: Writer, platforms: dict[str, Platform], submit: Callable[[Action, dict[str, Any]], Decision], safety=None, factcheck=None):
        super().__init__(llm, store, brand)
        self.writer, self.platforms, self.submit, self.safety, self.factcheck = writer, platforms, submit, safety, factcheck

    def collect(self, days: int = 14) -> int:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
        new = 0
        for row in self.store.list_content(status="published", limit=300):
            if (row.get("published_at") or "") < since or not row.get("remote_id"):
                continue
            p = self.platforms.get(row["platform"])
            if not p:
                continue
            for c in p.fetch_engagement([row["remote_id"]]):
                if self.store.add_engagement(p.name, row["id"], c.remote_id, c.author, c.text):
                    new += 1
        return new

    def respond(self) -> list[dict[str, Any]]:
        results = []
        for e in self.store.pending_engagement():
            p = self.platforms.get(e["platform"])
            post = self.store.get_content(e["content_id"]) if e.get("content_id") else None
            if not p or not post:
                self.store.mark_replied(e["id"])
                continue
            draft = self.writer.reply(p.name, post.get("body") or post.get("title") or "", e["author"], e["text"])
            if draft.get("skip"):
                self.store.mark_replied(e["id"])
                results.append({"engagement": e["id"], "skipped": draft.get("reason", "")})
                continue
            if self.factcheck:
                facts = self.factcheck.facts_for((post.get("meta") or {}).get("link", ""))
                r = self.factcheck.verify(draft["text"], facts, kind="reply")
                if not r.ok:
                    self.store.mark_replied(e["id"])
                    results.append({"engagement": e["id"], "verdict": "deny", "reason": "reply failed the fact check"})
                    continue
                draft["text"] = r.text
            verdict = self.safety.check(draft["text"]) if self.safety else None
            if verdict is not None and not verdict.ok:
                results.append({"engagement": e["id"], "verdict": "deny", "reason": f"safety: {verdict.reason}"})
                continue
            action = Action(ActionKind.REPLY_OWN, p.name, {"text": draft["text"], "reply_to": e["remote_comment_id"], "engagement_id": e["id"], "content_id": post["id"]}, safety_passed=True if verdict is None or verdict.ok else False)
            decision = self.submit(action, {"comment": Comment(e["remote_comment_id"], e["author"], e["text"], post.get("remote_id", ""))})
            results.append({"engagement": e["id"], "verdict": decision.verdict.value, "reason": decision.reason})
        return results
