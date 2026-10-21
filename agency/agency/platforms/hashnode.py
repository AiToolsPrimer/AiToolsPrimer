from __future__ import annotations

import os

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class Hashnode(Platform):
    name = "hashnode"
    label = "Hashnode"
    kinds = {"article"}
    env = ("HASHNODE_TOKEN", "HASHNODE_PUBLICATION_ID")
    signup_url = "https://hashnode.com/settings/developer"
    api_docs = "https://apidocs.hashnode.com"
    free_tier_note = "Free. Personal access token from Settings > Developer."

    def _publish(self, item: PublishItem) -> PublishResult:
        query = """mutation PublishPost($input: PublishPostInput!) { publishPost(input: $input) { post { id url } } }"""
        variables = {"input": {"title": item.title, "contentMarkdown": item.text, "publicationId": os.environ["HASHNODE_PUBLICATION_ID"], "tags": [{"name": t, "slug": t.lower().replace(" ", "-")} for t in item.tags[:5]], "originalArticleURL": item.link or None}}
        out = self._json(self.http.post("https://gql.hashnode.com", headers={"Authorization": os.environ["HASHNODE_TOKEN"]}, json={"query": query, "variables": variables}))
        if out.get("errors"):
            return PublishResult(False, error=str(out["errors"])[:300])
        post = out["data"]["publishPost"]["post"]
        return PublishResult(True, remote_id=post["id"], url=post["url"])
