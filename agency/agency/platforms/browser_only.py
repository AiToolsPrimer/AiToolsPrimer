"""Platforms that have no usable public API: the browser operator (or you) publishes them.
Each is a Platform so the director can plan for it, but ``publish`` never calls an API."""
from __future__ import annotations

from urllib.parse import quote

from agency.platforms.base import Platform, PublishItem, PublishResult


class _BrowserOnly(Platform):
    env = ()
    publish_modes = ("browser", "manual", "off")

    def configured(self) -> bool:
        return True

    def _publish(self, item: PublishItem) -> PublishResult:
        return PublishResult(False, error=f"{self.name}: no API; use browser or manual mode")


class Substack(_BrowserOnly):
    name = "substack"
    label = "Substack"
    kinds = {"article", "post"}
    signup_url = "https://substack.com"
    api_docs = "https://support.substack.com"
    free_tier_note = "No API. The operator writes the post in the Substack editor; you finish the publish dialog. Set SUBSTACK_PUBLICATION (the subdomain) in .env."


class LinkedInArticles(_BrowserOnly):
    name = "linkedin_articles"
    label = "LinkedIn Articles"
    kinds = {"article"}
    signup_url = "https://www.linkedin.com"
    api_docs = "https://www.linkedin.com/help/linkedin/answer/a522358"
    free_tier_note = "Long-form articles have no API; the operator fills the article editor, you click Publish."


class Blogger(_BrowserOnly):
    name = "blogger"
    label = "Blogger"
    kinds = {"article"}
    signup_url = "https://www.blogger.com"
    api_docs = "https://developers.google.com/blogger"
    free_tier_note = "Blogger's API needs an OAuth app; the browser route needs BLOGGER_BLOG_ID in .env."


class Dailymotion(_BrowserOnly):
    name = "dailymotion"
    label = "Dailymotion"
    kinds = {"video"}
    signup_url = "https://www.dailymotion.com/partner"
    api_docs = "https://developers.dailymotion.com/api/"
    free_tier_note = "Upload through the partner page in the agent's Chrome; you confirm the publish."


class Flipboard(Platform):
    name = "flipboard"
    label = "Flipboard"
    kinds = {"link"}
    env = ()
    publish_modes = ("intent", "manual", "off")
    signup_url = "https://flipboard.com"
    api_docs = "https://about.flipboard.com/publishers/"
    free_tier_note = "One tap: the intent link opens Flipboard with the guide ready to flip into your magazine."

    def configured(self) -> bool:
        return True

    @staticmethod
    def intent_url(item: PublishItem) -> str:
        return f"https://share.flipboard.com/bookmarklet/popout?v=2&title={quote(item.title or '')}&url={quote(item.link or '')}"

    def _publish(self, item: PublishItem) -> PublishResult:
        return PublishResult(False, error="flipboard: intent only")


class Quora(_BrowserOnly):
    name = "quora"
    label = "Quora"
    kinds = {"answer"}
    publish_modes = ("manual", "off")
    signup_url = "https://www.quora.com"
    api_docs = "https://help.quora.com"
    free_tier_note = "Drafts only: rewrite in your words before posting (Quora collapses generated answers)."


class HackerNews(_BrowserOnly):
    name = "hackernews"
    label = "Hacker News"
    kinds = {"link"}
    publish_modes = ("manual", "off")
    signup_url = "https://news.ycombinator.com"
    api_docs = "https://news.ycombinator.com/newsguidelines.html"
    free_tier_note = "Fact cards only; HN forbids AI-written text."


class StackExchange(_BrowserOnly):
    name = "stackexchange"
    label = "Stack Exchange"
    kinds = {"answer"}
    publish_modes = ("manual", "off")
    signup_url = "https://stackexchange.com"
    api_docs = "https://meta.stackexchange.com/help/gen-ai-policy"
    free_tier_note = "Fact cards only; generated answers are banned."
