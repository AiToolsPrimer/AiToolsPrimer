from __future__ import annotations

import os

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class DevTo(Platform):
    name = "devto"
    label = "DEV Community"
    kinds = {"article"}
    env = ("DEVTO_API_KEY",)
    signup_url = "https://dev.to/settings/extensions"
    api_docs = "https://developers.forem.com/api"
    free_tier_note = "Free. API key from Settings > Extensions."

    def _publish(self, item: PublishItem) -> PublishResult:
        body = {"article": {"title": item.title, "body_markdown": item.text, "published": item.extra.get("published", True), "tags": [t.replace("-", "").lower() for t in item.tags[:4]], "canonical_url": item.link or None}}
        out = self._json(self.http.post("https://dev.to/api/articles", headers={"api-key": os.environ["DEVTO_API_KEY"]}, json=body))
        return PublishResult(True, remote_id=str(out.get("id", "")), url=out.get("url", ""))

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        data = self._json(self.http.get(f"https://dev.to/api/articles/{remote_id}"))
        return Metrics(impressions=data.get("page_views_count"), likes=data.get("public_reactions_count"), replies=data.get("comments_count"), raw={})
