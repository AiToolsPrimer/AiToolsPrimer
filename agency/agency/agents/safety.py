"""The safety gate: brand rules first (cheap, deterministic), then the guard model."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from agency.agents.base import Agent
from agency.llm.client import LLMError, LocalLLM, Message
from agency.settings import Brand

PAYMENT_WORDS = re.compile(r"\b(buy now|limited offer|discount code|promo code|affiliate|sponsored|paid partnership|use my link|crypto|airdrop|giveaway)\b", re.I)
UNVERIFIED_NUM = re.compile(r"\b\d{2,}(\.\d+)?\s?(%|\b(percent|users|downloads|x faster|times faster)\b)", re.I)


@dataclass
class SafetyVerdict:
    ok: bool
    reason: str = ""
    category: str = ""


class Safety(Agent):
    role = "trust and safety editor"
    desk = "safety"
    temperature = 0.0

    def __init__(self, llm: LocalLLM, store, brand: Brand, guard: LocalLLM | None = None, allowed_link_hosts: tuple[str, ...] = ()):
        super().__init__(llm, store, brand)
        self.guard = guard
        own = urlsplit(brand.site).hostname or ""
        self.allowed_hosts = tuple(h for h in (own, *allowed_link_hosts) if h)

    def check(self, text: str, facts_supplied: bool = False) -> SafetyVerdict:
        low = text.lower()
        for claim in self.brand.banned_claims:
            if claim.lower() in low:
                return SafetyVerdict(False, f"banned claim: '{claim}'", "brand")
        if PAYMENT_WORDS.search(text):
            return SafetyVerdict(False, f"commercial wording: '{PAYMENT_WORDS.search(text).group(0)}'", "brand")
        if "[" in text and "]" in text and re.search(r"\[[^\]]{3,}\]", text):
            return SafetyVerdict(False, "unverified placeholder left in text", "verification")
        if not facts_supplied and UNVERIFIED_NUM.search(text):
            return SafetyVerdict(False, f"number without a supplied source: '{UNVERIFIED_NUM.search(text).group(0)}'", "verification")
        for url in re.findall(r"https?://[^\s)\]]+", text):
            host = urlsplit(url).hostname or ""
            if self.allowed_hosts and not any(host == h or host.endswith("." + h) for h in self.allowed_hosts):
                return SafetyVerdict(False, f"link to a host outside the allowlist: {host}", "links")
        if self.guard:
            v = self._guard_model(text)
            if not v.ok:
                return v
        return SafetyVerdict(True, "ok")

    def _guard_model(self, text: str) -> SafetyVerdict:
        try:
            out = self.guard.chat([Message("user", text)], temperature=0.0, max_tokens=64).text
        except LLMError:
            return SafetyVerdict(True, "guard model unavailable; brand rules passed")
        m = re.search(r"Safety:\s*(Safe|Unsafe|Controversial)", out, re.I)
        label = (m.group(1) if m else out.strip().split()[0] if out.strip() else "Safe").lower()
        if label == "unsafe":
            cat = re.search(r"Categories?:\s*(.+)", out)
            return SafetyVerdict(False, "guard model flagged the text as unsafe", cat.group(1).strip() if cat else "unsafe")
        return SafetyVerdict(True, "ok")
