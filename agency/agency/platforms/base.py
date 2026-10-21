from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from agency.safety.payment_guard import GuardedHTTP


class PlatformError(RuntimeError):
    pass


@dataclass
class PublishItem:
    kind: str                       # post | article | video | image | short
    text: str = ""                  # post body or article markdown
    title: str = ""
    link: str = ""
    tags: list[str] = field(default_factory=list)
    media: list[Path] = field(default_factory=list)   # images or a single video
    alt_texts: list[str] = field(default_factory=list)
    thumbnail: Path | None = None
    reply_to: str | None = None     # remote id to reply to
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResult:
    ok: bool
    remote_id: str = ""
    url: str = ""
    error: str = ""
    dry_run: bool = False


@dataclass
class Comment:
    remote_id: str
    author: str
    text: str
    parent_remote_id: str = ""      # our post the comment is under


@dataclass
class Metrics:
    impressions: int | None = None
    likes: int | None = None
    replies: int | None = None
    shares: int | None = None
    clicks: int | None = None
    followers: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class Platform:
    """Base connector. Subclasses set ``name``, ``kinds``, ``char_limit``, ``env`` and implement ``_publish``."""

    name: ClassVar[str] = "base"
    label: ClassVar[str] = "Base"
    kinds: ClassVar[set[str]] = {"post"}
    char_limit: ClassVar[int] = 0            # 0 = no hard limit
    env: ClassVar[tuple[str, ...]] = ()      # required environment variables
    signup_url: ClassVar[str] = ""
    api_docs: ClassVar[str] = ""
    free_tier_note: ClassVar[str] = ""
    publish_modes: ClassVar[tuple[str, ...]] = ("api", "browser", "intent", "manual", "off")

    def __init__(self, http: GuardedHTTP, dry_run: bool = True, extra: dict[str, Any] | None = None):
        self.http = http
        self.dry_run = dry_run
        self.extra = extra or {}

    # ------------------------------------------------------------------ config
    def configured(self) -> bool:
        return all(os.environ.get(v) for v in self.env)

    def missing_env(self) -> list[str]:
        return [v for v in self.env if not os.environ.get(v)]

    def creds(self) -> dict[str, str]:
        return {v: os.environ.get(v, "") for v in self.env}

    def supports(self, kind: str) -> bool:
        return kind in self.kinds

    def fit(self, item: PublishItem) -> PublishItem:
        """Trim text to the platform limit, keeping the link intact."""
        if self.char_limit and len(item.text) > self.char_limit:
            keep = self.char_limit - 1
            item.text = item.text[:keep].rsplit(" ", 1)[0] + "…"
        return item

    # ------------------------------------------------------------------ public API
    def publish(self, item: PublishItem) -> PublishResult:
        if not self.supports(item.kind):
            return PublishResult(False, error=f"{self.name} does not accept {item.kind}")
        item = self.fit(item)
        if self.dry_run:
            return PublishResult(True, remote_id=f"dry-{self.name}", url=f"dry-run://{self.name}", dry_run=True)
        if not self.configured():
            return PublishResult(False, error=f"{self.name}: missing {', '.join(self.missing_env())}")
        try:
            return self._publish(item)
        except Exception as e:  # noqa: BLE001 - connectors report, never crash the agency
            return PublishResult(False, error=f"{self.name}: {e}")

    def reply(self, comment: Comment, text: str) -> PublishResult:
        return self.publish(PublishItem(kind="post", text=text, reply_to=comment.remote_id))

    def fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        if self.dry_run or not self.configured():
            return []
        try:
            return self._fetch_engagement(remote_ids)
        except Exception:  # noqa: BLE001
            return []

    def fetch_metrics(self, remote_id: str) -> Metrics:
        if self.dry_run or not self.configured():
            return Metrics()
        try:
            return self._fetch_metrics(remote_id)
        except Exception:  # noqa: BLE001
            return Metrics()

    # ------------------------------------------------------------------ to implement
    def _publish(self, item: PublishItem) -> PublishResult:
        raise NotImplementedError

    def _fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        return []

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        return Metrics()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _json(r: Any) -> Any:
        if r.status_code >= 400:
            raise PlatformError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}
