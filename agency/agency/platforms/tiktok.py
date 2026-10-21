from __future__ import annotations

import os

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class TikTok(Platform):
    name = "tiktok"
    label = "TikTok"
    kinds = {"short", "video"}
    char_limit = 2200
    env = ("TIKTOK_ACCESS_TOKEN",)
    signup_url = "https://developers.tiktok.com/apps"
    api_docs = "https://developers.tiktok.com/doc/content-posting-api-get-started"
    free_tier_note = "Free. Direct Post needs an audited app; until audited, posts land as private drafts in the creator inbox."
    base = "https://open.tiktokapis.com/v2"

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {os.environ['TIKTOK_ACCESS_TOKEN']}", "Content-Type": "application/json; charset=UTF-8"}

    def _publish(self, item: PublishItem) -> PublishResult:
        if not item.media:
            return PublishResult(False, error="tiktok needs a video")
        video = item.media[0]
        size = video.stat().st_size
        caption = (item.title + "\n" + item.text + " " + " ".join(f"#{t}" for t in item.tags[:8]))[:2200]
        init = self._json(self.http.post(f"{self.base}/post/publish/video/init/", headers=self.headers, json={
            "post_info": {"title": caption, "privacy_level": item.extra.get("privacy", "PUBLIC_TO_EVERYONE"), "disable_duet": False, "disable_comment": False, "disable_stitch": False, "video_cover_timestamp_ms": 1000},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
        }))
        data = init.get("data", {})
        if not data.get("upload_url"):
            return PublishResult(False, error=str(init.get("error")))
        self.http.put(data["upload_url"], headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size-1}/{size}"}, content=video.read_bytes())
        return PublishResult(True, remote_id=data.get("publish_id", ""))

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        return Metrics()
