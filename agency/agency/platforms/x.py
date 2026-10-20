from __future__ import annotations

import os

from agency.platforms import oauth1
from agency.platforms.base import Comment, Metrics, Platform, PublishItem, PublishResult


class X(Platform):
    name = "x"
    label = "X"
    kinds = {"post", "image"}
    char_limit = 280
    env = ("X_CONSUMER_KEY", "X_CONSUMER_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
    signup_url = "https://developer.x.com"
    api_docs = "https://docs.x.com/x-api"
    free_tier_note = "Free tier: write-only, 500 posts/month per app; reading replies and metrics needs a paid tier, so engagement is skipped on free."

    def _auth(self, method: str, url: str, params: dict | None = None) -> dict:
        c = self.creds()
        return {"Authorization": oauth1.sign(method, url, params or {}, c["X_CONSUMER_KEY"], c["X_CONSUMER_SECRET"], c["X_ACCESS_TOKEN"], c["X_ACCESS_TOKEN_SECRET"])}

    def _publish(self, item: PublishItem) -> PublishResult:
        body: dict = {"text": item.text if not item.link or item.link in item.text else f"{item.text} {item.link}"}
        media_ids = []
        for path in item.media[:4]:
            url = "https://upload.twitter.com/1.1/media/upload.json"
            r = self.http.post(url, headers=self._auth("POST", url), files={"media": (path.name, path.read_bytes())})
            media_ids.append(self._json(r)["media_id_string"])
        if media_ids:
            body["media"] = {"media_ids": media_ids}
        if item.reply_to:
            body["reply"] = {"in_reply_to_tweet_id": item.reply_to}
        url = "https://api.x.com/2/tweets"
        out = self._json(self.http.post(url, headers={**self._auth("POST", url), "Content-Type": "application/json"}, json=body))
        tid = out["data"]["id"]
        return PublishResult(True, remote_id=tid, url=f"https://x.com/i/status/{tid}")

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        url = f"https://api.x.com/2/tweets/{remote_id}"
        params = {"tweet.fields": "public_metrics"}
        data = self._json(self.http.get(url, headers=self._auth("GET", url, params), params=params))
        m = data.get("data", {}).get("public_metrics", {})
        return Metrics(impressions=m.get("impression_count"), likes=m.get("like_count"), replies=m.get("reply_count"), shares=(m.get("retweet_count") or 0) + (m.get("quote_count") or 0), raw=m)
