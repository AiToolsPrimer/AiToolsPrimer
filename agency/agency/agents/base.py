from __future__ import annotations

from typing import Any

from contextlib import contextmanager

from agency.llm.client import LocalLLM, Message
from agency.memory.store import Store
from agency.settings import Brand


class Agent:
    role: str = "agent"
    desk: str = "director"          # which desk in the office this agent sits at
    temperature: float = 0.6
    office = None                   # Office, injected by the app

    def __init__(self, llm: LocalLLM, store: Store, brand: Brand):
        self.llm, self.store, self.brand = llm, store, brand

    def report(self, task: str, steps: int = 0):
        """Context manager: shows this agent as working on ``task`` in the office."""
        if self.office is None:
            return _noop()
        return self.office.working(self.desk, task, steps)

    def progress(self, step: str, index: int | None = None, count: int | None = None) -> None:
        if self.office is not None:
            self.office.step(self.desk, step, index, count)

    def system(self, extra: str = "") -> str:
        b = self.brand
        return (
            f"You are the {self.role} of the in-house marketing team for {b.name} ({b.site}).\n"
            f"Tagline: {b.tagline}\nAudience: {b.audience}\nContent pillars: {'; '.join(b.pillars)}\n"
            f"Voice: {b.voice}\nEverything you write is in {'English' if b.language == 'en' else b.language}.\n"
            f"Never use these phrases or claims: {', '.join(b.banned_claims)}. Never invent facts, prices, "
            f"features or statistics; if a fact is needed and not supplied, write it as a placeholder in "
            f"[square brackets] so a human can verify it. Never ask people to pay for anything.\n{extra}"
        ).strip()

    def ask_json(self, user: str, *, extra_system: str = "", schema: dict[str, Any] | None = None, temperature: float | None = None) -> Any:
        return self.llm.complete_json(self.system(extra_system), user, schema=schema, temperature=self.temperature if temperature is None else temperature)

    def ask_text(self, user: str, *, extra_system: str = "", temperature: float | None = None, max_tokens: int = 4096) -> str:
        res = self.llm.chat([Message("system", self.system(extra_system)), Message("user", user)], temperature=self.temperature if temperature is None else temperature, max_tokens=max_tokens)
        return res.text.strip()

    def memory_context(self, query: str, k: int = 5) -> str:
        hits = self.store.recall(query, k=k)
        if not hits:
            return "(no related memory)"
        return "\n".join(f"- [{h['ref_table']}#{h['ref_id']}] {h['text'][:300]}" for h in hits)


@contextmanager
def _noop():
    yield
