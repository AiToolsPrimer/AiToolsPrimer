from __future__ import annotations

from agency.platforms.base import Platform, PublishItem, PublishResult


class Medium(Platform):
    """Medium closed its publishing API to new integration tokens. Articles for Medium are
    produced as Markdown in the approval queue for a manual paste-in (import by URL also works)."""

    name = "medium"
    label = "Medium"
    kinds = {"article"}
    env = ()
    publish_modes = ("browser", "manual", "off")
    signup_url = "https://medium.com"
    api_docs = "https://medium.com/p/import"
    free_tier_note = "No public API any more. The agency prepares the article; you import it from the canonical URL on your site."

    def configured(self) -> bool:
        return True

    def _publish(self, item: PublishItem) -> PublishResult:
        return PublishResult(False, error="medium has no publishing API; use Import from URL")
