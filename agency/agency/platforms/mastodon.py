from __future__ import annotations

import os

from agency.platforms.base import Comment, Metrics, Platform, PublishItem, PublishResult


class Mastodon(Platform):
    name = "mastodon"
    label = "Mastodon"
    kinds = {"post", "image", "video"}
    char_limit = 500
    env = ("MASTODON_INSTANCE", "MASTODON_ACCESS_TOKEN")
    signup_url = "https://joinmastodon.org"
    api_docs = "https://docs.joinmastodon.org/api/"
    free_tier_note = "Free. Token from Preferences > Development > New application (scopes: read write)."

    @property
    def base(self) -> str:
        return os.environ["MASTODON_INSTANCE"].rstrip("/")

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {os.environ['MASTODON_ACCESS_TOKEN']}"}

    def _publish(self, item: PublishItem) -> PublishResult:
        media_ids = []
        for i, path in enumerate(item.media[:4]):
            r = self.http.post(f"{self.base}/api/v2/media", headers=self.headers, files={"file": (path.name, path.read_bytes())}, data={"description": item.alt_texts[i] if i < len(item.alt_texts) else item.title})
            media_ids.append(self._json(r)["id"])
        text = item.text if not item.link or item.link in item.text else f"{item.text}\n\n{item.link}"
        body = {"status": text, "media_ids": media_ids, "language": "en"}
        if item.reply_to:
            body["in_reply_to_id"] = item.reply_to
        out = self._json(self.http.post(f"{self.base}/api/v1/statuses", headers=self.headers, json=body))
        return PublishResult(True, remote_id=out["id"], url=out.get("url", ""))

    def _fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        me = self._json(self.http.get(f"{self.base}/api/v1/accounts/verify_credentials", headers=self.headers))["id"]
        out = []
        for rid in remote_ids:
            ctx = self._json(self.http.get(f"{self.base}/api/v1/statuses/{rid}/context", headers=self.headers))
            for s in ctx.get("descendants", []):
                if s["account"]["id"] != me and s.get("in_reply_to_id") == rid:
                    out.append(Comment(remote_id=s["id"], author=s["account"]["acct"], text=_strip(s.get("content", "")), parent_remote_id=rid))
        return out

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        s = self._json(self.http.get(f"{self.base}/api/v1/statuses/{remote_id}", headers=self.headers))
        return Metrics(likes=s.get("favourites_count"), replies=s.get("replies_count"), shares=s.get("reblogs_count"), raw=s)


def _strip(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html).strip()
