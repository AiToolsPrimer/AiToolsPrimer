"""The knowledge base: one Markdown card per platform (YAML front-matter with the hard
limits, prose with the algorithm, the rules and what works) plus cross-cutting playbooks
(virality, compliance, formats, cadence).  Agents read the cards into their prompts; code
enforces the front-matter limits so a model cannot talk its way past them."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class Card:
    key: str
    path: Path
    meta: dict[str, Any]
    body: str

    @property
    def label(self) -> str:
        return self.meta.get("label", self.key)

    def section(self, title: str) -> str:
        m = re.search(rf"^##\s+{re.escape(title)}\s*\n(.*?)(?=^##\s|\Z)", self.body, re.S | re.M)
        return m.group(1).strip() if m else ""

    def brief(self, max_chars: int = 3500) -> str:
        """What the writer sees: limits first, then the playbook, trimmed."""
        limits = {k: v for k, v in self.meta.items() if k not in ("sources", "label", "kinds", "last_checked")}
        text = f"# {self.label}\nHard limits (enforced by code): {limits}\n\n{self.body}"
        return text[:max_chars]

    def stale(self, days: int = 45) -> bool:
        lc = self.meta.get("last_checked")
        if not lc:
            return True
        try:
            d = dt.date.fromisoformat(str(lc))
        except ValueError:
            return True
        return (dt.date.today() - d).days > days


@dataclass
class Constraints:
    char_limit: int = 0
    hashtags_max: int | None = None
    link_policy: str = "ok"             # ok | in-first-comment | penalized | not-clickable | none
    ai_label: str = "none"              # none | recommended | required-for-realistic-ai | required
    ai_label_text: str = ""
    title_limit: int = 0
    tags_max: int | None = None
    media: dict[str, Any] = field(default_factory=dict)
    cadence: dict[str, Any] = field(default_factory=dict)
    first_line_hook: bool = True

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> "Constraints":
        return cls(
            char_limit=int(meta.get("char_limit", 0) or 0),
            hashtags_max=meta.get("hashtags_max"),
            link_policy=str(meta.get("link_policy", "ok")),
            ai_label=str(meta.get("ai_label", "none")),
            ai_label_text=str(meta.get("ai_label_text", "")),
            title_limit=int(meta.get("title_limit", 0) or 0),
            tags_max=meta.get("tags_max"),
            media=dict(meta.get("media", {}) or {}),
            cadence=dict(meta.get("cadence", {}) or {}),
            first_line_hook=bool(meta.get("first_line_hook", True)),
        )


class KnowledgeBase:
    def __init__(self, root: Path):
        self.root = root
        self.cards: dict[str, Card] = {}
        self.playbooks: dict[str, Card] = {}
        self.reload()

    def reload(self) -> None:
        self.cards = {c.key: c for c in (self._load(p) for p in sorted((self.root / "platforms").glob("*.md")))}
        self.playbooks = {c.key: c for c in (self._load(p) for p in sorted((self.root / "playbooks").glob("*.md")))}

    @staticmethod
    def _load(path: Path) -> Card:
        text = path.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        body = text
        m = FRONT.match(text)
        if m:
            meta = yaml.safe_load(m.group(1)) or {}
            body = text[m.end():]
        return Card(key=path.stem, path=path, meta=meta, body=body.strip())

    def card(self, platform: str) -> Card | None:
        return self.cards.get(platform)

    def constraints(self, platform: str) -> Constraints:
        c = self.cards.get(platform)
        return Constraints.from_meta(c.meta) if c else Constraints()

    def brief(self, platform: str, max_chars: int = 3500) -> str:
        c = self.cards.get(platform)
        return c.brief(max_chars) if c else f"(no knowledge card for {platform}: keep it short, specific and useful)"

    def playbook(self, name: str, max_chars: int = 4000) -> str:
        c = self.playbooks.get(name)
        return c.body[:max_chars] if c else ""

    def stale_cards(self, days: int = 45) -> list[Card]:
        return [c for c in self.cards.values() if c.stale(days)]

    def set_meta(self, platform: str, field_name: str, value: Any) -> None:
        c = self.cards[platform]
        meta = dict(c.meta)
        if field_name in ("char_limit", "hashtags_max", "title_limit", "tags_max"):
            try:
                value = int(str(value).strip())
            except ValueError:
                return
        meta[field_name] = value
        c.path.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + c.body.strip() + "\n", encoding="utf-8")
        self.reload()

    def apply_update(self, platform: str, note: str, source: str = "", checked: dt.date | None = None) -> None:
        """Append a dated note to the card's 'Updates' section and bump last_checked."""
        c = self.cards[platform]
        checked = checked or dt.date.today()
        body = c.body
        entry = f"- {checked.isoformat()}: {note}" + (f" (source: {source})" if source else "")
        if re.search(r"^##\s+Updates\s*$", body, re.M):
            body = re.sub(r"(^##\s+Updates\s*\n)", rf"\1{entry}\n", body, count=1, flags=re.M)
        else:
            body = body.rstrip() + f"\n\n## Updates\n{entry}\n"
        meta = dict(c.meta)
        meta["last_checked"] = checked.isoformat()
        c.path.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + body.strip() + "\n", encoding="utf-8")
        self.reload()


# ----------------------------------------------------------------------------- enforcement

HASHTAG = re.compile(r"(?<!\w)#\w+")
URL = re.compile(r"https?://\S+")


def check_constraints(text: str, platform: str, c: Constraints, title: str = "", is_ai_generated_media: bool = False) -> list[str]:
    """Return the list of violations (empty = fine). Pure code: no model involved."""
    problems: list[str] = []
    if c.char_limit and len(text) > c.char_limit:
        problems.append(f"{platform}: {len(text)} characters, limit {c.char_limit}")
    if c.title_limit and title and len(title) > c.title_limit:
        problems.append(f"{platform}: title {len(title)} characters, limit {c.title_limit}")
    tags = HASHTAG.findall(text)
    if c.hashtags_max is not None and len(tags) > c.hashtags_max:
        problems.append(f"{platform}: {len(tags)} hashtags, max {c.hashtags_max}")
    urls = URL.findall(text)
    if c.link_policy == "none" and urls:
        problems.append(f"{platform}: links are not allowed in the body")
    if c.link_policy == "in-first-comment" and urls:
        problems.append(f"{platform}: put the link in the first comment, not in the post")
    if c.ai_label in ("required", "required-for-realistic-ai") and is_ai_generated_media and c.ai_label_text and c.ai_label_text.lower() not in text.lower():
        problems.append(f"{platform}: AI-generated media needs the label '{c.ai_label_text}'")
    return problems


def fix_for_platform(text: str, c: Constraints, link: str = "") -> tuple[str, str]:
    """Deterministic repairs: move the link to a 'first comment' slot, trim extra hashtags, trim length.
    Returns (text, first_comment)."""
    first_comment = ""
    if c.link_policy == "in-first-comment":
        urls = URL.findall(text)
        for u in urls:
            text = text.replace(u, "").strip()
        first_comment = (urls[0] if urls else link) or ""
        text = re.sub(r"[ \t]+\n", "\n", text)
    if c.hashtags_max is not None:
        tags = HASHTAG.findall(text)
        if len(tags) > c.hashtags_max:
            for t in tags[c.hashtags_max:]:
                text = text.replace(t, "", 1)
            text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if c.char_limit and len(text) > c.char_limit:
        keep = text[: c.char_limit - 1]
        cut = keep.rfind(". ")
        text = (keep[: cut + 1] if cut > c.char_limit * 0.6 else keep.rsplit(" ", 1)[0] + "…").strip()
    return text, first_comment
