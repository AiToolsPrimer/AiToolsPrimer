from __future__ import annotations

import os

from agency.platforms import oauth1
from agency.platforms.base import Platform, PublishItem, PublishResult


class Tumblr(Platform):
    name = "tumblr"
    label = "Tumblr"
    kinds = {"post", "image", "article"}
    env = ("TUMBLR_CONSUMER_KEY", "TUMBLR_CONSUMER_SECRET", "TUMBLR_TOKEN", "TUMBLR_TOKEN_SECRET", "TUMBLR_BLOG")
    signup_url = "https://www.tumblr.com/oauth/apps"
    api_docs = "https://www.tumblr.com/docs/en/api/v2"
    free_tier_note = "Free."

    def _publish(self, item: PublishItem) -> PublishResult:
        c = self.creds()
        url = f"https://api.tumblr.com/v2/blog/{c['TUMBLR_BLOG']}/post"
        params = {"type": "text", "title": item.title, "body": item.text + (f"\n\n{item.link}" if item.link else ""), "tags": ",".join(item.tags), "format": "markdown"}
        headers = {"Authorization": oauth1.sign("POST", url, params, c["TUMBLR_CONSUMER_KEY"], c["TUMBLR_CONSUMER_SECRET"], c["TUMBLR_TOKEN"], c["TUMBLR_TOKEN_SECRET"])}
        out = self._json(self.http.post(url, headers=headers, data=params))
        pid = str(out.get("response", {}).get("id", ""))
        return PublishResult(True, remote_id=pid, url=f"https://{c['TUMBLR_BLOG']}/post/{pid}")
