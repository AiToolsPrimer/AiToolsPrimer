"""The policy engine: every outgoing action is a proposal until this says yes.

An ``Action`` is anything that touches the outside world: a post, a reply, a
video upload, a metrics pull, a scout search.  The engine checks it against the
runtime toggles, the hard guarantees, per-platform rate limits and quiet hours,
then returns ``allow``, ``queue`` (needs a human click) or ``deny`` with a reason.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from agency.settings import Limits, Toggles


class ActionKind(str, Enum):
    PUBLISH_POST = "publish_post"
    PUBLISH_ARTICLE = "publish_article"
    PUBLISH_VIDEO = "publish_video"
    REPLY_OWN = "reply_own"            # answer a comment under our own content
    DRAFT_EXTERNAL = "draft_external"  # draft a reply on someone else's post (never sent by us)
    READ_METRICS = "read_metrics"
    READ_ENGAGEMENT = "read_engagement"
    SCOUT_SEARCH = "scout_search"
    SIGNUP_KIT = "signup_kit"
    BROWSER_PUBLISH = "browser_publish"   # the operator fills the post; you click Publish
    BROWSER_COMMENT = "browser_comment"   # the operator fills a comment; you click Reply
    PREPARE_MANUAL = "prepare_manual"     # intent link / copy-paste package; nothing leaves the machine
    READ_MAIL = "read_mail"
    NETWORK_WATCH = "network_watch"
    EXTERNAL_COMMENT = "external_comment"   # a comment under someone else's post, through the API, after your approval
    # Things that are always refused, kept here so the UI can explain why
    CREATE_ACCOUNT = "create_account"
    FRIEND_REQUEST = "friend_request"
    MASS_COMMENT = "mass_comment"
    PAYMENT = "payment"


class Verdict(str, Enum):
    ALLOW = "allow"
    QUEUE = "queue"
    DENY = "deny"


ALWAYS_DENIED = {
    ActionKind.CREATE_ACCOUNT: "account creation is a human step (block_account_creation)",
    ActionKind.FRIEND_REQUEST: "automated friend/follow requests violate platform terms (block_mass_actions)",
    ActionKind.MASS_COMMENT: "automated commenting on other people's content violates platform terms (block_mass_actions)",
    ActionKind.PAYMENT: "nothing is ever paid for (block_payments)",
}

TOGGLE_FOR_KIND = {
    ActionKind.PUBLISH_POST: "write_posts",
    ActionKind.PUBLISH_ARTICLE: "write_articles",
    ActionKind.PUBLISH_VIDEO: "make_videos",
    ActionKind.REPLY_OWN: "auto_reply_own_posts",
    ActionKind.DRAFT_EXTERNAL: "draft_external_engagement",
    ActionKind.READ_METRICS: "collect_metrics",
    ActionKind.READ_ENGAGEMENT: "collect_metrics",
    ActionKind.SCOUT_SEARCH: "discover_platforms",
    ActionKind.SIGNUP_KIT: "prepare_signup_kits",
    ActionKind.BROWSER_PUBLISH: "browser_operator",
    ActionKind.BROWSER_COMMENT: "browser_operator",
    ActionKind.PREPARE_MANUAL: "write_posts",
    ActionKind.READ_MAIL: "read_mail",
    ActionKind.NETWORK_WATCH: "network_watch",
    ActionKind.EXTERNAL_COMMENT: "network_watch",
}

BROWSER_KINDS = {ActionKind.BROWSER_PUBLISH, ActionKind.BROWSER_COMMENT, ActionKind.EXTERNAL_COMMENT}  # all need a human click

OUTBOUND_KINDS = {ActionKind.PUBLISH_POST, ActionKind.PUBLISH_ARTICLE, ActionKind.PUBLISH_VIDEO, ActionKind.REPLY_OWN, ActionKind.BROWSER_PUBLISH, ActionKind.BROWSER_COMMENT, ActionKind.EXTERNAL_COMMENT}


@dataclass
class Action:
    kind: ActionKind
    platform: str
    payload: dict[str, Any] = field(default_factory=dict)
    cost_estimate: float = 0.0           # must stay 0.0; anything else is denied
    safety_passed: bool | None = None    # result of the safety agent, None = not checked yet
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


@dataclass
class Decision:
    verdict: Verdict
    reason: str

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


class PolicyEngine:
    def __init__(
        self,
        toggles: Toggles,
        limits: Limits,
        count_recent: Callable[[str, ActionKind, dt.timedelta], int] | None = None,
        now: Callable[[], dt.datetime] | None = None,
    ):
        self.toggles = toggles
        self.limits = limits
        self.count_recent = count_recent or (lambda platform, kind, window: 0)
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))

    def evaluate(self, action: Action) -> Decision:
        t = self.toggles
        if action.kind in ALWAYS_DENIED:
            return Decision(Verdict.DENY, ALWAYS_DENIED[action.kind])
        if action.cost_estimate != 0.0:
            return Decision(Verdict.DENY, f"action has a cost ({action.cost_estimate}); nothing is ever paid for")
        if not t.get("master_enabled"):
            return Decision(Verdict.DENY, "master switch is off")
        toggle = TOGGLE_FOR_KIND.get(action.kind)
        if toggle and not t.get(toggle):
            return Decision(Verdict.DENY, f"switch '{toggle}' is off")
        if action.kind in OUTBOUND_KINDS:
            if not t.platform_enabled(action.platform):
                return Decision(Verdict.DENY, f"platform '{action.platform}' is switched off")
            if action.safety_passed is False:
                return Decision(Verdict.DENY, "content failed the safety check")
            if action.safety_passed is None:
                return Decision(Verdict.DENY, "content has not been through the safety check")
            if self._in_quiet_hours():
                return Decision(Verdict.QUEUE, "quiet hours: held until the window closes")
            limit_reason = self._rate_limited(action)
            if limit_reason:
                return Decision(Verdict.QUEUE, limit_reason)
            if action.kind in BROWSER_KINDS:
                # a browser action is never automatic: the human click in the browser IS the approval
                if not t.get("publishing") and not action.payload.get("human_click"):
                    return Decision(Verdict.QUEUE, "publishing switch is off: held in the approval queue")
                return Decision(Verdict.ALLOW, "ok") if action.payload.get("human_click") else Decision(Verdict.QUEUE, "browser action: waits for your click")
            if not t.get("publishing"):
                return Decision(Verdict.QUEUE, "publishing switch is off: held in the approval queue")
            if t.get("approval_required"):
                return Decision(Verdict.QUEUE, "approval required: waiting for a human click")
        return Decision(Verdict.ALLOW, "ok")

    def _in_quiet_hours(self) -> bool:
        start, end = self.limits.quiet_hours_utc
        hour = self.now().hour
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def _rate_limited(self, action: Action) -> str | None:
        day, hour = dt.timedelta(days=1), dt.timedelta(hours=1)
        if action.kind in {ActionKind.PUBLISH_POST, ActionKind.PUBLISH_ARTICLE, ActionKind.PUBLISH_VIDEO}:
            n = self.count_recent(action.platform, action.kind, day)
            if n >= self.limits.posts_per_platform_per_day:
                return f"daily limit reached on {action.platform} ({n}/{self.limits.posts_per_platform_per_day})"
        if action.kind is ActionKind.REPLY_OWN:
            n = self.count_recent(action.platform, action.kind, hour)
            if n >= self.limits.replies_per_platform_per_hour:
                return f"hourly reply limit reached on {action.platform}"
        if action.kind in BROWSER_KINDS:
            n = self.count_recent("*browser*", action.kind, day)
            if n >= self.limits.browser_actions_per_day:
                return f"daily browser action limit reached ({n}/{self.limits.browser_actions_per_day})"
        return None
