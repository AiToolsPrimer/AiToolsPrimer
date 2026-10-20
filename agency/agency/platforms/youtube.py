from __future__ import annotations

import json
import os

from agency.platforms.base import Comment, Metrics, Platform, PublishItem, PublishResult


class YouTube(Platform):
    name = "youtube"
    label = "YouTube"
    kinds = {"video", "short"}
    env = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    signup_url = "https://console.cloud.google.com/apis/library/youtube.googleapis.com"
    api_docs = "https://developers.google.com/youtube/v3"
    free_tier_note = "Free. 10,000 quota units/day; one upload costs 1,600 (about 6 uploads/day)."

    def _token(self) -> str:
        r = self.http.post("https://oauth2.googleapis.com/token", data={"client_id": os.environ["YOUTUBE_CLIENT_ID"], "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"], "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token"})
        return self._json(r)["access_token"]

    def _publish(self, item: PublishItem) -> PublishResult:
        if not item.media:
            return PublishResult(False, error="youtube needs a video file")
        token = self._token()
        video = item.media[0]
        title = item.title[:100]
        if item.kind == "short" and "#Shorts" not in title:
            title = (title + " #Shorts")[:100]
        meta = {
            "snippet": {"title": title, "description": (item.text + ("\n\n" + item.link if item.link else ""))[:5000], "tags": item.tags[:30], "categoryId": item.extra.get("categoryId", "28"), "defaultLanguage": "en"},
            "status": {"privacyStatus": item.extra.get("privacy", "public"), "selfDeclaredMadeForKids": False},
        }
        init = self.http.post(
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(video.stat().st_size)},
            content=json.dumps(meta),
        )
        if init.status_code >= 400:
            return PublishResult(False, error=f"upload init HTTP {init.status_code}: {init.text[:200]}")
        upload_url = init.headers["Location"]
        up = self.http.put(upload_url, headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"}, content=video.read_bytes())
        data = self._json(up)
        vid = data["id"]
        if item.thumbnail and item.thumbnail.exists():
            self.http.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}", headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"}, content=item.thumbnail.read_bytes())
        return PublishResult(True, remote_id=vid, url=f"https://youtu.be/{vid}")

    def _fetch_engagement(self, remote_ids: list[str]) -> list[Comment]:
        token = self._token()
        out = []
        for vid in remote_ids:
            data = self._json(self.http.get("https://www.googleapis.com/youtube/v3/commentThreads", headers={"Authorization": f"Bearer {token}"}, params={"part": "snippet", "videoId": vid, "maxResults": 50, "order": "time"}))
            for t in data.get("items", []):
                top = t["snippet"]["topLevelComment"]["snippet"]
                if t["snippet"].get("totalReplyCount", 0) == 0:
                    out.append(Comment(remote_id=t["snippet"]["topLevelComment"]["id"], author=top.get("authorDisplayName", ""), text=top.get("textOriginal", ""), parent_remote_id=vid))
        return out

    def reply(self, comment: Comment, text: str) -> PublishResult:
        if self.dry_run:
            return PublishResult(True, remote_id="dry-youtube-reply", dry_run=True)
        token = self._token()
        r = self.http.post("https://www.googleapis.com/youtube/v3/comments?part=snippet", headers={"Authorization": f"Bearer {token}"}, json={"snippet": {"parentId": comment.remote_id, "textOriginal": text}})
        data = self._json(r)
        return PublishResult(True, remote_id=data.get("id", ""))

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        token = self._token()
        data = self._json(self.http.get("https://www.googleapis.com/youtube/v3/videos", headers={"Authorization": f"Bearer {token}"}, params={"part": "statistics", "id": remote_id}))
        items = data.get("items", [])
        if not items:
            return Metrics()
        s = items[0]["statistics"]
        return Metrics(impressions=int(s.get("viewCount", 0)), likes=int(s.get("likeCount", 0)), replies=int(s.get("commentCount", 0)), raw=s)
