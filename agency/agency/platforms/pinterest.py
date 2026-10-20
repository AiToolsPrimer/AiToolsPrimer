from __future__ import annotations

import base64
import os

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class Pinterest(Platform):
    name = "pinterest"
    label = "Pinterest"
    kinds = {"image"}
    char_limit = 500
    env = ("PINTEREST_ACCESS_TOKEN", "PINTEREST_BOARD_ID")
    signup_url = "https://developers.pinterest.com/apps/"
    api_docs = "https://developers.pinterest.com/docs/api/v5/"
    free_tier_note = "Free (trial access until the app is approved for standard access)."

    def _publish(self, item: PublishItem) -> PublishResult:
        if not item.media:
            return PublishResult(False, error="pinterest needs an image")
        b64 = base64.b64encode(item.media[0].read_bytes()).decode()
        body = {"board_id": os.environ["PINTEREST_BOARD_ID"], "title": item.title[:100], "description": item.text[:500], "link": item.link or None, "alt_text": item.alt_texts[0] if item.alt_texts else item.title, "media_source": {"source_type": "image_base64", "content_type": "image/png", "data": b64}}
        out = self._json(self.http.post("https://api.pinterest.com/v5/pins", headers={"Authorization": f"Bearer {os.environ['PINTEREST_ACCESS_TOKEN']}"}, json=body))
        return PublishResult(True, remote_id=out.get("id", ""), url=f"https://www.pinterest.com/pin/{out.get('id','')}/")

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        data = self._json(self.http.get(f"https://api.pinterest.com/v5/pins/{remote_id}/analytics", headers={"Authorization": f"Bearer {os.environ['PINTEREST_ACCESS_TOKEN']}"}, params={"start_date": "2024-01-01", "end_date": "2030-01-01", "metric_types": "IMPRESSION,SAVE,PIN_CLICK"}))
        m = data.get("all", {}).get("lifetime_metrics", {})
        return Metrics(impressions=m.get("IMPRESSION"), shares=m.get("SAVE"), clicks=m.get("PIN_CLICK"), raw=m)
