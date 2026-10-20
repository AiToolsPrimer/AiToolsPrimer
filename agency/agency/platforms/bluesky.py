from __future__ import annotations

import datetime as dt
import os
import re

from agency.platforms.base import Comment, Metrics, Platform, PublishItem, PublishResult

URL_RE = re.compile(r"https?://[^\s)]+")


class Bluesky(Platform):
    name = "bluesky"
    label = "Bluesky"
    kinds = {"post", "image"}
    char_limit = 300
    env = ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD")
    signup_url = "https://bsky.app"
    api_docs = "https://docs.bsky.app"
    free_tier_note = "Free. App password from Settings > Privacy and Security > App Passwords."
    pds = "https://bsky.social"

    def _session(self) -> dict:
        r = self.http.post(f"{self.pds}/xrpc/com.atproto.server.createSession", json={"identifier": os.environ["BLUESKY_HANDLE"], "password": os.environ["BLUESKY_APP_PASSWORD"]})
        return self._json(r)

    def _facets(self, text: str) -> list[dict]:
        facets = []
        for m in URL_RE.finditer(text):
            start = len(text[: m.start()].encode("utf-8"))
            end = len(text[: m.end()].encode("utf-8"))
            facets.append({"index": {"byteStart": start, "byteEnd": end}, "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}]})
        return facets

    def _publish(self, item: PublishItem) -> PublishResult:
        s = self._session()
        headers = {"Authorization": f"Bearer {s['accessJwt']}"}
        record: dict = {"$type": "app.bsky.feed.post", "text": item.text, "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(), "facets": self._facets(item.text)}
        if item.media:
            images = []
            for i, path in enumerate(item.media[:4]):
                blob = self._json(self.http.post(f"{self.pds}/xrpc/com.atproto.repo.uploadBlob", headers={**headers, "Content-Type": "image/png"}, content=path.read_bytes()))["blob"]
                images.append({"image": blob, "alt": item.alt_texts[i] if i < len(item.alt_texts) else item.title})
            record["embed"] = {"$type": "app.bsky.embed.images", "images": images}
        elif item.link:
            record["embed"] = {"$type": "app.bsky.embed.external", "external": {"uri": item.link, "title": item.title or item.link, "description": ""}}
        if item.reply_to:
            uri, cid = item.reply_to.split("|", 1)
            record["reply"] = {"root": {"uri": uri, "cid": cid}, "parent": {"uri": uri, "cid": cid}}
        out = self._json(self.http.post(f"{self.pds}/xrpc/com.atproto.repo.createRecord", headers=headers, json={"repo": s["did"], "collection": "app.bsky.feed.post", "record": record}))
        rkey = out["uri"].rsplit("/", 1)[-1]
        return PublishResult(True, remote_id=f"{out['uri']}|{out['cid']}", url=f"https://bsky.app/profile/{s['handle']}/post/{rkey}")

    def _fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        s = self._session()
        headers = {"Authorization": f"Bearer {s['accessJwt']}"}
        comments: list[Comment] = []
        for rid in remote_ids:
            uri = rid.split("|", 1)[0]
            thread = self._json(self.http.get("https://api.bsky.app/xrpc/app.bsky.feed.getPostThread", headers=headers, params={"uri": uri, "depth": 1}))
            for reply in thread.get("thread", {}).get("replies", []):
                p = reply.get("post", {})
                if p.get("author", {}).get("did") == s["did"]:
                    continue
                comments.append(Comment(remote_id=f"{p['uri']}|{p['cid']}", author=p["author"]["handle"], text=p["record"].get("text", ""), parent_remote_id=rid))
        return comments

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        uri = remote_id.split("|", 1)[0]
        data = self._json(self.http.get("https://api.bsky.app/xrpc/app.bsky.feed.getPosts", params={"uris": uri}))
        posts = data.get("posts", [])
        if not posts:
            return Metrics()
        p = posts[0]
        return Metrics(likes=p.get("likeCount"), replies=p.get("replyCount"), shares=(p.get("repostCount") or 0) + (p.get("quoteCount") or 0), raw=p)
