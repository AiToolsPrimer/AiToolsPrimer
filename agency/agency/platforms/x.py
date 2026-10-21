"""X: the API has no free tier any more (closed 6 February 2026; $0.015 per post, $0.20 with a link),
so under the no-payment rule the agency never publishes to X through the API.  Posts for X are
prepared for the browser operator (you click Publish) or as an intent link (one tap, pre-filled)."""
from __future__ import annotations

from urllib.parse import quote

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class X(Platform):
    name = "x"
    label = "X"
    kinds = {"post", "image"}
    char_limit = 280
    env = ()
    signup_url = "https://x.com"
    api_docs = "https://docs.x.com/x-api"
    free_tier_note = "API is pay-per-post since Feb 2026, so X is browser-with-your-click or one-tap intent only. Reads are also paid: no metrics or comments are collected."
    publish_modes = ("browser", "intent", "manual", "off")

    def configured(self) -> bool:
        return True  # nothing to configure: the browser profile holds your login

    @staticmethod
    def intent_url(item: PublishItem) -> str:
        text = item.text if not item.link or item.link in item.text else f"{item.text} {item.link}"
        return "https://x.com/intent/post?text=" + quote(text, safe="")

    def _publish(self, item: PublishItem) -> PublishResult:
        return PublishResult(False, error="x: API publishing is disabled (paid). Use browser or intent mode.")

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        return Metrics()
