from __future__ import annotations

import os

from agency.platforms.base import Comment, Metrics, Platform, PublishItem, PublishResult


class Reddit(Platform):
    name = "reddit"
    label = "Reddit"
    kinds = {"post", "article"}
    char_limit = 40000
    env = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME", "REDDIT_PASSWORD", "REDDIT_SUBREDDIT")
    signup_url = "https://www.reddit.com/prefs/apps"
    api_docs = "https://www.reddit.com/dev/api/"
    free_tier_note = "Free for a 'script' app under the API terms (100 req/min). Post only to subreddits whose rules allow self-promotion; r/u_<username> profile is always fine."

    def _token(self) -> str:
        r = self.http.post("https://www.reddit.com/api/v1/access_token", auth=(os.environ["REDDIT_CLIENT_ID"], os.environ["REDDIT_CLIENT_SECRET"]), data={"grant_type": "password", "username": os.environ["REDDIT_USERNAME"], "password": os.environ["REDDIT_PASSWORD"]})
        return self._json(r)["access_token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}"}

    def _publish(self, item: PublishItem) -> PublishResult:
        h = self._headers()
        if item.reply_to:
            out = self._json(self.http.post("https://oauth.reddit.com/api/comment", headers=h, data={"api_type": "json", "thing_id": item.reply_to, "text": item.text}))
            things = out.get("json", {}).get("data", {}).get("things", [])
            rid = things[0]["data"]["name"] if things else ""
            return PublishResult(True, remote_id=rid)
        sr = item.extra.get("subreddit") or os.environ["REDDIT_SUBREDDIT"]
        body = {"api_type": "json", "sr": sr, "title": item.title[:300], "kind": "self", "text": item.text, "sendreplies": "true"}
        if item.link and item.kind == "post" and not item.text:
            body.update({"kind": "link", "url": item.link})
        out = self._json(self.http.post("https://oauth.reddit.com/api/submit", headers=h, data=body))
        data = out.get("json", {}).get("data", {})
        if out.get("json", {}).get("errors"):
            return PublishResult(False, error=str(out["json"]["errors"]))
        return PublishResult(True, remote_id=data.get("name", ""), url=data.get("url", ""))

    def _fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        h = self._headers()
        me = os.environ["REDDIT_USERNAME"]
        out = []
        for rid in remote_ids:
            pid = rid.split("_", 1)[-1]
            data = self._json(self.http.get(f"https://oauth.reddit.com/comments/{pid}", headers=h, params={"depth": 1, "limit": 50}))
            if len(data) < 2:
                continue
            for child in data[1]["data"]["children"]:
                d = child.get("data", {})
                if d.get("author") and d["author"] != me and d.get("body"):
                    out.append(Comment(remote_id=d["name"], author=d["author"], text=d["body"], parent_remote_id=rid))
        return out

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        data = self._json(self.http.get("https://oauth.reddit.com/api/info", headers=self._headers(), params={"id": remote_id}))
        children = data.get("data", {}).get("children", [])
        if not children:
            return Metrics()
        d = children[0]["data"]
        return Metrics(likes=d.get("score"), replies=d.get("num_comments"), raw={"upvote_ratio": d.get("upvote_ratio")})
