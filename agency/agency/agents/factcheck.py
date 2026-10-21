"""Sentence-level fact verification.

Every piece of text that will leave the machine is checked against the *facts of the
guide it links to*: the checker fetches the guide once, extracts atomic facts, and then
classifies every sentence of the draft as supported (by which facts), an unsupported
claim (removed), or a sentence with no factual claim (kept).  Numbers get a second,
purely mechanical check: a number that does not appear in the facts does not survive.
Promise words ("free", "safe", "best", "tested"...) survive only if the facts say so.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agency.agents.base import Agent
from agency.safety.payment_guard import GuardedHTTP

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
NUMBER = re.compile(r"(?<![\w/#@])(\$?\d[\d,]*(?:\.\d+)?%?)(?![\w/])")
COUNT_NOUNS = {"tools", "tool", "steps", "step", "ways", "things", "tips", "apps", "options", "editors", "settings", "questions", "reasons", "slides", "parts", "guides", "checks", "points", "mistakes", "rules", "formats", "platforms", "scenes"}
PROMISES = re.compile(r"\b(free|safe|secure|best|fastest|cheapest|easiest|tested|guaranteed|proven|unlimited|instant|#1|100%|no risk|risk-free)\b", re.I)
ENGLISH_STOPWORDS = {"the", "and", "to", "of", "a", "in", "is", "it", "you", "that", "for", "on", "with", "this", "we", "are", "be", "or", "not", "your", "what", "how", "when", "if", "one", "can", "our", "from", "by", "an", "at", "as", "but", "they", "so", "all", "just", "more", "about"}
TAG_RE = re.compile(r"<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>", re.S | re.I)


def looks_english(text: str, min_ratio: float = 0.12) -> bool:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if len(words) < 6:
        return True  # too short to judge (hashtags, a link)
    hits = sum(1 for w in words if w in ENGLISH_STOPWORDS)
    non_ascii = sum(1 for ch in text if ord(ch) > 127 and ch.isalpha())
    return hits / len(words) >= min_ratio and non_ascii / max(1, len(text)) < 0.08


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for para in re.split(r"\n+", text):
        para = para.strip()
        if not para:
            continue
        parts.extend(s.strip() for s in SENTENCE_SPLIT.split(para) if s.strip())
    return parts


def html_to_text(html: str, max_chars: int = 60000) -> str:
    html = TAG_RE.sub(" ", html)
    html = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</tr>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:max_chars]


def _norm_number(n: str) -> str:
    return n.replace(",", "").replace("$", "").strip()


def number_check(sentence: str, facts_text: str) -> list[str]:
    """Numbers in the sentence that do not appear in the facts (list counts of small size are allowed)."""
    fact_numbers = {_norm_number(n) for n in NUMBER.findall(facts_text)}
    bad = []
    for m in NUMBER.finditer(sentence):
        raw = m.group(1)
        n = _norm_number(raw)
        if n in fact_numbers or n.rstrip("%") in fact_numbers:
            continue
        after = sentence[m.end():].strip().split(" ")[0].strip(",.:;").lower() if sentence[m.end():].strip() else ""
        try:
            val = float(n.rstrip("%"))
        except ValueError:
            continue
        if not raw.endswith("%") and not raw.startswith("$") and val <= 20 and after in COUNT_NOUNS:
            continue
        if re.fullmatch(r"(19|20)\d\d", n):   # a year is a date, not a measurement
            continue
        bad.append(raw)
    return bad


@dataclass
class VerifyResult:
    text: str
    kept: list[str] = field(default_factory=list)
    removed: list[dict[str, str]] = field(default_factory=list)
    supported: int = 0
    facts_used: list[str] = field(default_factory=list)
    language_ok: bool = True

    @property
    def ok(self) -> bool:
        return self.language_ok and bool(self.text.strip())

    def report(self) -> dict[str, Any]:
        return {"kept": len(self.kept), "removed": self.removed, "supported": self.supported, "facts_used": self.facts_used, "language_ok": self.language_ok}


class FactChecker(Agent):
    role = "fact checker"
    temperature = 0.0

    def __init__(self, llm, store, brand, http: GuardedHTTP):
        super().__init__(llm, store, brand)
        self.http = http

    # ------------------------------------------------------------------ facts
    def facts_for(self, url: str, refresh: bool = False) -> list[dict[str, str]]:
        if not url:
            return []
        if not refresh:
            cached = self.store.get_facts(url)
            if cached is not None:
                return cached
        try:
            r = self.http.get(url, headers={"Accept": "text/html"})
            if r.status_code >= 400:
                return []
            text = html_to_text(r.text)
        except Exception:  # noqa: BLE001
            return []
        if not text:
            return []
        data = self.ask_json(
            f"Extract every atomic fact from this page that a marketing writer could rely on: numbers, prices, limits, features, dates, test results, verdicts, what was checked and when. "
            f"One fact per item, with the exact quote. Do not infer, do not generalize, do not add facts that are not on the page.\n\nPage ({url}):\n{text[:40000]}\n\n"
            'Return JSON: {"facts": [{"id": "F1", "fact": "...", "quote": "...", "kind": "number|price|limit|feature|date|verdict|method|other"}]}'
        )
        facts = [f for f in (data.get("facts", []) if isinstance(data, dict) else []) if f.get("fact")]
        for i, f in enumerate(facts):
            f["id"] = f.get("id") or f"F{i+1}"
        self.store.set_facts(url, facts)
        return facts

    @staticmethod
    def facts_text(facts: list[dict[str, str]]) -> str:
        return "\n".join(f"[{f['id']}] {f['fact']}" + (f" (quote: \"{f['quote']}\")" if f.get("quote") else "") for f in facts)

    # ------------------------------------------------------------------ verification
    def verify(self, text: str, facts: list[dict[str, str]], *, kind: str = "post", allow_promises_from: str = "") -> VerifyResult:
        result = VerifyResult(text=text)
        if not looks_english(text):
            result.language_ok = False
            result.text = ""
            result.removed.append({"sentence": text[:120], "reason": "not English"})
            return result
        sentences = split_sentences(text)
        if not sentences:
            return result
        ftext = self.facts_text(facts)
        promise_source = (ftext + " " + allow_promises_from).lower()
        # 1) mechanical checks
        mech: dict[int, str] = {}
        for i, s in enumerate(sentences):
            bad = number_check(s, ftext)
            if bad:
                mech[i] = f"number not in the facts: {', '.join(bad)}"
                continue
            for m in PROMISES.finditer(s):
                w = m.group(1).lower()
                if w not in promise_source:
                    mech[i] = f"promise word without a fact behind it: '{w}'"
                    break
        # 2) model classification of the remaining sentences, in one call
        to_judge = [(i, s) for i, s in enumerate(sentences) if i not in mech]
        verdicts: dict[int, dict[str, Any]] = {}
        if to_judge and facts:
            data = self.ask_json(
                f"Facts from the source guide:\n{ftext}\n\nSentences from a draft {kind}:\n" + "\n".join(f"S{i}: {s}" for i, s in to_judge) +
                "\n\nFor each sentence decide: 'supported' (which fact ids back every claim in it), 'unsupported' (it asserts something the facts do not say, or contradicts them), "
                "or 'no_claim' (a question, an opinion clearly marked as ours, a call to action, framing with no checkable assertion). Be strict: a sentence with one unsupported claim is 'unsupported'.\n"
                'Return JSON: {"verdicts": [{"id": "S0", "verdict": "supported|unsupported|no_claim", "facts": ["F1"], "why": "short"}]}',
            )
            for v in (data.get("verdicts", []) if isinstance(data, dict) else []):
                try:
                    idx = int(str(v.get("id", "")).lstrip("S"))
                except ValueError:
                    continue
                verdicts[idx] = v
        elif to_judge and not facts:
            data = self.ask_json(
                f"There are NO verified facts for this {kind}. Sentences:\n" + "\n".join(f"S{i}: {s}" for i, s in to_judge) +
                "\n\nMark every sentence that asserts a checkable fact (about a product, price, feature, number, safety, performance, what was tested) as 'unsupported'; "
                "mark questions, calls to action, clearly-marked opinions and framing as 'no_claim'.\n"
                'Return JSON: {"verdicts": [{"id": "S0", "verdict": "unsupported|no_claim", "why": "short"}]}',
            )
            for v in (data.get("verdicts", []) if isinstance(data, dict) else []):
                try:
                    verdicts[int(str(v.get("id", "")).lstrip("S"))] = v
                except ValueError:
                    continue
        kept, used = [], set()
        for i, s in enumerate(sentences):
            if i in mech:
                result.removed.append({"sentence": s, "reason": mech[i]})
                continue
            v = verdicts.get(i)
            verdict = (v or {}).get("verdict", "no_claim" if not facts else "supported")
            if verdict == "unsupported":
                result.removed.append({"sentence": s, "reason": (v or {}).get("why", "not supported by the guide")})
                continue
            if verdict == "supported":
                result.supported += 1
                used.update(str(f) for f in (v or {}).get("facts", []) or [])
            kept.append(s)
        result.kept = kept
        result.facts_used = sorted(used)
        result.text = _rejoin(text, kept)
        return result

    def verify_scenes(self, scenes: list[dict[str, Any]], facts: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Verify every scene narration of a video script in one pass; drop scenes left empty."""
        removed_all: list[dict[str, str]] = []
        out = []
        for sc in scenes:
            r = self.verify(sc.get("narration", ""), facts, kind="video narration")
            removed_all.extend(r.removed)
            if r.text.strip():
                out.append({**sc, "narration": r.text})
        return out, removed_all


def _rejoin(original: str, kept: list[str]) -> str:
    """Rebuild the text keeping the original paragraph breaks where possible."""
    if not kept:
        return ""
    paras = []
    for para in re.split(r"\n+", original):
        ps = [s for s in split_sentences(para) if s in kept]
        if ps:
            paras.append(" ".join(ps))
    return "\n\n".join(paras) if paras else " ".join(kept)
