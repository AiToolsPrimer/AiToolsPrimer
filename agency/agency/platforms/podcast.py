"""A podcast feed from the articles: each episode is the article read by the local voice,
with a spoken disclosure that the host is an AI voice.  The agency writes the RSS and
the MP3s into assets/podcast/; you host that folder on the site (or any static host) and
submit the feed URL once to Apple, Spotify and the others."""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import Any

from agency.media.ffmpeg import FF

INTRO = "This episode is read by an AI voice. The facts come from the guides on {site}, where you can see what was checked and when."


class PodcastFeed:
    def __init__(self, out_dir: Path, site: str, title: str, description: str, public_base_url: str, ff: FF, author: str = "", artwork_url: str = ""):
        self.out_dir, self.site, self.title, self.description, self.base, self.ff = out_dir, site, title, description, public_base_url.rstrip("/"), ff
        self.author, self.artwork_url = author, artwork_url
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def add_episode(self, slug: str, title: str, summary: str, wav: Path, link: str, published: dt.datetime | None = None) -> Path:
        mp3 = self.out_dir / f"{slug}.mp3"
        self.ff._run(["-i", str(wav), "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", str(mp3)])
        meta = {"slug": slug, "title": title, "summary": summary, "link": link, "mp3": mp3.name, "bytes": mp3.stat().st_size, "seconds": round(self.ff.duration(mp3)), "published": (published or dt.datetime.now(dt.timezone.utc)).strftime("%a, %d %b %Y %H:%M:%S +0000")}
        (self.out_dir / f"{slug}.json").write_text(_json(meta))
        self.write_feed()
        return mp3

    def episodes(self) -> list[dict[str, Any]]:
        import json
        eps = [json.loads(p.read_text()) for p in self.out_dir.glob("*.json")]
        return sorted(eps, key=lambda e: e["published"], reverse=True)

    def write_feed(self) -> Path:
        items = []
        for e in self.episodes():
            url = f"{self.base}/{e['mp3']}"
            items.append(
                f"<item><title>{html.escape(e['title'])}</title><link>{html.escape(e['link'])}</link><guid isPermaLink=\"false\">{html.escape(e['slug'])}</guid>"
                f"<pubDate>{e['published']}</pubDate><description>{html.escape(e['summary'])}</description>"
                f"<enclosure url=\"{html.escape(url)}\" length=\"{e['bytes']}\" type=\"audio/mpeg\"/><itunes:duration>{e['seconds']}</itunes:duration><itunes:explicit>false</itunes:explicit></item>"
            )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>'
            f"<title>{html.escape(self.title)}</title><link>{html.escape(self.site)}</link><language>en</language><description>{html.escape(self.description)}</description>"
            f"<itunes:author>{html.escape(self.author or self.title)}</itunes:author><itunes:explicit>false</itunes:explicit>"
            + (f'<itunes:image href="{html.escape(self.artwork_url)}"/>' if self.artwork_url else "")
            + f'<atom:link href="{html.escape(self.base)}/feed.xml" rel="self" type="application/rss+xml"/>'
            + "".join(items) + "</channel></rss>\n"
        )
        feed = self.out_dir / "feed.xml"
        feed.write_text(xml)
        return feed


def _json(d: dict[str, Any]) -> str:
    import json
    return json.dumps(d, indent=2)
