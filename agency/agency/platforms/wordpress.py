from __future__ import annotations

import base64
import os

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class WordPress(Platform):
    name = "wordpress"
    label = "WordPress (self-hosted or .com)"
    kinds = {"article"}
    env = ("WORDPRESS_URL", "WORDPRESS_USER", "WORDPRESS_APP_PASSWORD")
    signup_url = "https://wordpress.org"
    api_docs = "https://developer.wordpress.org/rest-api/"
    free_tier_note = "Free. Application password from Users > Profile."

    @property
    def headers(self) -> dict:
        tok = base64.b64encode(f"{os.environ['WORDPRESS_USER']}:{os.environ['WORDPRESS_APP_PASSWORD']}".encode()).decode()
        return {"Authorization": f"Basic {tok}"}

    def _publish(self, item: PublishItem) -> PublishResult:
        base = os.environ["WORDPRESS_URL"].rstrip("/")
        featured = None
        if item.media:
            r = self.http.post(f"{base}/wp-json/wp/v2/media", headers={**self.headers, "Content-Disposition": f'attachment; filename="{item.media[0].name}"', "Content-Type": "image/png"}, content=item.media[0].read_bytes())
            featured = self._json(r).get("id")
        body = {"title": item.title, "content": _md_to_html(item.text), "status": item.extra.get("status", "publish"), "excerpt": item.extra.get("excerpt", "")}
        if featured:
            body["featured_media"] = featured
        out = self._json(self.http.post(f"{base}/wp-json/wp/v2/posts", headers=self.headers, json=body))
        return PublishResult(True, remote_id=str(out.get("id", "")), url=out.get("link", ""))


def _md_to_html(md: str) -> str:
    """Tiny Markdown → HTML for headings, paragraphs, lists and links. WordPress tidies the rest."""
    import re
    html, in_list = [], False
    for line in md.splitlines():
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", line)
        if line.startswith("- ") or line.startswith("* "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{line[2:]}</li>")
            continue
        if in_list:
            html.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            n = len(m.group(1))
            html.append(f"<h{n}>{m.group(2)}</h{n}>")
        elif line.strip():
            html.append(f"<p>{line}</p>")
    if in_list:
        html.append("</ul>")
    return "\n".join(html)
