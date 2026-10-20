from __future__ import annotations

import os

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class LinkedIn(Platform):
    name = "linkedin"
    label = "LinkedIn"
    kinds = {"post", "image", "article"}
    char_limit = 3000
    env = ("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_AUTHOR_URN")
    signup_url = "https://www.linkedin.com/developers/apps"
    api_docs = "https://learn.microsoft.com/linkedin/marketing/community-management/shares/posts-api"
    free_tier_note = "Free. Needs the 'Share on LinkedIn' product (w_member_social). Author URN looks like urn:li:person:XXXX or urn:li:organization:NNNN."

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}", "LinkedIn-Version": "202409", "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"}

    def _publish(self, item: PublishItem) -> PublishResult:
        author = os.environ["LINKEDIN_AUTHOR_URN"]
        if item.reply_to:
            out = self.http.post(f"https://api.linkedin.com/rest/socialActions/{item.reply_to}/comments", headers=self.headers, json={"actor": author, "message": {"text": item.text}})
            return PublishResult(True, remote_id=self._json(out).get("id", ""))
        body: dict = {"author": author, "commentary": item.text, "visibility": "PUBLIC", "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}, "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        if item.media:
            init = self._json(self.http.post("https://api.linkedin.com/rest/images?action=initializeUpload", headers=self.headers, json={"initializeUploadRequest": {"owner": author}}))["value"]
            self.http.put(init["uploadUrl"], headers={"Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}"}, content=item.media[0].read_bytes())
            body["content"] = {"media": {"id": init["image"], "altText": item.alt_texts[0] if item.alt_texts else item.title}}
        elif item.link:
            body["content"] = {"article": {"source": item.link, "title": item.title or item.link}}
        r = self.http.post("https://api.linkedin.com/rest/posts", headers=self.headers, json=body)
        if r.status_code >= 400:
            return PublishResult(False, error=f"HTTP {r.status_code}: {r.text[:200]}")
        pid = r.headers.get("x-restli-id", "")
        return PublishResult(True, remote_id=pid, url=f"https://www.linkedin.com/feed/update/{pid}")

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        data = self._json(self.http.get(f"https://api.linkedin.com/rest/socialActions/{remote_id}", headers=self.headers))
        return Metrics(likes=data.get("likesSummary", {}).get("totalLikes"), replies=data.get("commentsSummary", {}).get("totalFirstLevelComments"), raw=data)
