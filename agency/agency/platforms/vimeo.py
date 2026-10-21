from __future__ import annotations

import os

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class Vimeo(Platform):
    name = "vimeo"
    label = "Vimeo"
    kinds = {"video"}
    char_limit = 5000
    env = ("VIMEO_ACCESS_TOKEN",)
    signup_url = "https://developer.vimeo.com/apps"
    api_docs = "https://developer.vimeo.com/api/upload/videos"
    free_tier_note = "Free plan with weekly upload limits. Personal access token with upload + edit scopes."

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {os.environ['VIMEO_ACCESS_TOKEN']}", "Accept": "application/vnd.vimeo.*+json;version=3.4"}

    def _publish(self, item: PublishItem) -> PublishResult:
        if not item.media:
            return PublishResult(False, error="vimeo needs a video file")
        video = item.media[0]
        size = video.stat().st_size
        create = self._json(self.http.post("https://api.vimeo.com/me/videos", headers=self.headers, json={"upload": {"approach": "tus", "size": size}, "name": item.title[:128], "description": (item.text + ("\n\n" + item.link if item.link else ""))[:5000], "privacy": {"view": item.extra.get("privacy", "anybody")}}))
        upload_link = create["upload"]["upload_link"]
        r = self.http.request("PATCH", upload_link, headers={"Tus-Resumable": "1.0.0", "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"}, content=video.read_bytes())
        if r.status_code >= 400:
            return PublishResult(False, error=f"tus upload HTTP {r.status_code}")
        return PublishResult(True, remote_id=create["uri"].rsplit("/", 1)[-1], url=create.get("link", ""))

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        data = self._json(self.http.get(f"https://api.vimeo.com/videos/{remote_id}", headers=self.headers, params={"fields": "stats.plays,metadata.connections.likes.total,metadata.connections.comments.total"}))
        return Metrics(impressions=data.get("stats", {}).get("plays"), likes=data.get("metadata", {}).get("connections", {}).get("likes", {}).get("total"), replies=data.get("metadata", {}).get("connections", {}).get("comments", {}).get("total"), raw=data)
