"""Official-API connectors. Every connector publishes only to accounts the owner
has connected with their own credentials, through the platform's public API."""
from __future__ import annotations

from agency.platforms.base import Platform, PublishItem, PublishResult, Comment, Metrics, PlatformError  # noqa: F401


def build_all(settings, http, dry_run: bool) -> dict[str, Platform]:
    from agency.platforms import bluesky, mastodon, x, youtube, reddit, telegram, meta, linkedin, tiktok, pinterest, wordpress, devto, hashnode, tumblr, medium

    classes = [
        bluesky.Bluesky, mastodon.Mastodon, x.X, youtube.YouTube, reddit.Reddit, telegram.Telegram,
        meta.FacebookPage, meta.Instagram, meta.Threads, linkedin.LinkedIn, tiktok.TikTok, pinterest.Pinterest,
        wordpress.WordPress, devto.DevTo, hashnode.Hashnode, tumblr.Tumblr, medium.Medium,
    ]
    out: dict[str, Platform] = {}
    for cls in classes:
        p = cls(http=http, dry_run=dry_run, extra=(settings.platforms.get(cls.name).extra if settings.platforms.get(cls.name) else {}))
        out[p.name] = p
    return out
