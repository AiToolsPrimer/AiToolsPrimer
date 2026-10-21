"""Facebook Page, Instagram (Business/Creator) and Threads via the Graph API."""
from __future__ import annotations

import os
import time

from agency.platforms.base import Comment, Metrics, Platform, PublishItem, PublishResult

GRAPH = "https://graph.facebook.com/v21.0"


class FacebookPage(Platform):
    name = "facebook"
    label = "Facebook Page"
    kinds = {"post", "image", "video", "article"}
    char_limit = 63206
    env = ("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN")
    signup_url = "https://developers.facebook.com/apps"
    api_docs = "https://developers.facebook.com/docs/pages-api"
    free_tier_note = "Free. Long-lived Page access token with pages_manage_posts, pages_read_engagement."

    def _publish(self, item: PublishItem) -> PublishResult:
        page, token = os.environ["FACEBOOK_PAGE_ID"], os.environ["FACEBOOK_PAGE_TOKEN"]
        if item.reply_to:
            out = self._json(self.http.post(f"{GRAPH}/{item.reply_to}/comments", data={"message": item.text, "access_token": token}))
            return PublishResult(True, remote_id=out.get("id", ""))
        if item.media and item.media[0].suffix.lower() in {".mp4", ".mov"}:
            out = self._json(self.http.post(f"{GRAPH}/{page}/videos", data={"description": item.text, "title": item.title, "access_token": token}, files={"source": (item.media[0].name, item.media[0].read_bytes())}))
        elif item.media:
            out = self._json(self.http.post(f"{GRAPH}/{page}/photos", data={"message": item.text, "access_token": token}, files={"source": (item.media[0].name, item.media[0].read_bytes())}))
        else:
            data = {"message": item.text, "access_token": token}
            if item.link:
                data["link"] = item.link
            out = self._json(self.http.post(f"{GRAPH}/{page}/feed", data=data))
        pid = out.get("post_id") or out.get("id", "")
        return PublishResult(True, remote_id=pid, url=f"https://www.facebook.com/{pid}")

    def _fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        token = os.environ["FACEBOOK_PAGE_TOKEN"]
        out = []
        for rid in remote_ids:
            data = self._json(self.http.get(f"{GRAPH}/{rid}/comments", params={"access_token": token, "fields": "id,from,message", "filter": "toplevel"}))
            for c in data.get("data", []):
                if c.get("from", {}).get("id") != os.environ["FACEBOOK_PAGE_ID"]:
                    out.append(Comment(remote_id=c["id"], author=c.get("from", {}).get("name", ""), text=c.get("message", ""), parent_remote_id=rid))
        return out

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        data = self._json(self.http.get(f"{GRAPH}/{remote_id}", params={"access_token": os.environ["FACEBOOK_PAGE_TOKEN"], "fields": "shares,likes.summary(true),comments.summary(true)"}))
        return Metrics(likes=data.get("likes", {}).get("summary", {}).get("total_count"), replies=data.get("comments", {}).get("summary", {}).get("total_count"), shares=data.get("shares", {}).get("count"), raw=data)


class Instagram(Platform):
    name = "instagram"
    label = "Instagram"
    kinds = {"image", "video", "short"}
    char_limit = 2200
    env = ("INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN", "PUBLIC_MEDIA_BASE_URL")
    signup_url = "https://developers.facebook.com/docs/instagram-platform"
    api_docs = "https://developers.facebook.com/docs/instagram-platform/content-publishing"
    free_tier_note = "Free. Needs a Business/Creator account. Media must be fetched from a public URL: PUBLIC_MEDIA_BASE_URL is where you host the file (your site works)."

    def _publish(self, item: PublishItem) -> PublishResult:
        uid, token = os.environ["INSTAGRAM_USER_ID"], os.environ["INSTAGRAM_ACCESS_TOKEN"]
        if item.reply_to:
            out = self._json(self.http.post(f"{GRAPH}/{item.reply_to}/replies", data={"message": item.text, "access_token": token}))
            return PublishResult(True, remote_id=out.get("id", ""))
        if not item.media:
            return PublishResult(False, error="instagram needs an image or video")
        public_url = item.extra.get("public_url") or f"{os.environ['PUBLIC_MEDIA_BASE_URL'].rstrip('/')}/{item.media[0].name}"
        caption = item.text + ("\n\n" + " ".join(f"#{t}" for t in item.tags[:20]) if item.tags else "")
        is_video = item.media[0].suffix.lower() in {".mp4", ".mov"}
        data = {"caption": caption[:2200], "access_token": token}
        if is_video:
            data.update({"media_type": "REELS", "video_url": public_url, "share_to_feed": "true"})
        else:
            data["image_url"] = public_url
        container = self._json(self.http.post(f"{GRAPH}/{uid}/media", data=data))["id"]
        for _ in range(30):
            status = self._json(self.http.get(f"{GRAPH}/{container}", params={"fields": "status_code", "access_token": token})).get("status_code")
            if status == "FINISHED":
                break
            if status == "ERROR":
                return PublishResult(False, error="instagram container processing failed")
            time.sleep(5)
        out = self._json(self.http.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": container, "access_token": token}))
        mid = out.get("id", "")
        link = self._json(self.http.get(f"{GRAPH}/{mid}", params={"fields": "permalink", "access_token": token})).get("permalink", "")
        return PublishResult(True, remote_id=mid, url=link)

    def _fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        token = os.environ["INSTAGRAM_ACCESS_TOKEN"]
        out = []
        for rid in remote_ids:
            data = self._json(self.http.get(f"{GRAPH}/{rid}/comments", params={"access_token": token, "fields": "id,username,text"}))
            for c in data.get("data", []):
                out.append(Comment(remote_id=c["id"], author=c.get("username", ""), text=c.get("text", ""), parent_remote_id=rid))
        return out

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        data = self._json(self.http.get(f"{GRAPH}/{remote_id}", params={"access_token": os.environ["INSTAGRAM_ACCESS_TOKEN"], "fields": "like_count,comments_count"}))
        return Metrics(likes=data.get("like_count"), replies=data.get("comments_count"), raw=data)


class Threads(Platform):
    name = "threads"
    label = "Threads"
    kinds = {"post", "image"}
    char_limit = 500
    env = ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN")
    signup_url = "https://developers.facebook.com/docs/threads"
    api_docs = "https://developers.facebook.com/docs/threads/posts"
    free_tier_note = "Free. Images need a public URL (PUBLIC_MEDIA_BASE_URL) like Instagram."
    base = "https://graph.threads.net/v1.0"

    def _publish(self, item: PublishItem) -> PublishResult:
        uid, token = os.environ["THREADS_USER_ID"], os.environ["THREADS_ACCESS_TOKEN"]
        data = {"media_type": "TEXT", "text": item.text, "access_token": token}
        if item.media and os.environ.get("PUBLIC_MEDIA_BASE_URL"):
            data.update({"media_type": "IMAGE", "image_url": f"{os.environ['PUBLIC_MEDIA_BASE_URL'].rstrip('/')}/{item.media[0].name}"})
        if item.reply_to:
            data["reply_to_id"] = item.reply_to
        if item.link and item.link not in item.text:
            data["link_attachment"] = item.link
        container = self._json(self.http.post(f"{self.base}/{uid}/threads", data=data))["id"]
        time.sleep(3)
        out = self._json(self.http.post(f"{self.base}/{uid}/threads_publish", data={"creation_id": container, "access_token": token}))
        mid = out.get("id", "")
        link = self._json(self.http.get(f"{self.base}/{mid}", params={"fields": "permalink", "access_token": token})).get("permalink", "")
        return PublishResult(True, remote_id=mid, url=link)

    def _fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        token = os.environ["THREADS_ACCESS_TOKEN"]
        out = []
        for rid in remote_ids:
            data = self._json(self.http.get(f"{self.base}/{rid}/replies", params={"access_token": token, "fields": "id,username,text"}))
            for c in data.get("data", []):
                out.append(Comment(remote_id=c["id"], author=c.get("username", ""), text=c.get("text", ""), parent_remote_id=rid))
        return out

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        data = self._json(self.http.get(f"{self.base}/{remote_id}/insights", params={"access_token": os.environ["THREADS_ACCESS_TOKEN"], "metric": "views,likes,replies,reposts"}))
        m = {d["name"]: (d.get("values", [{}])[0].get("value")) for d in data.get("data", [])}
        return Metrics(impressions=m.get("views"), likes=m.get("likes"), replies=m.get("replies"), shares=m.get("reposts"), raw=m)
