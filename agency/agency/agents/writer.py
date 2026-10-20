"""The writer: posts, threads, articles, captions and video scripts, per platform."""
from __future__ import annotations

from typing import Any

from agency.agents.base import Agent

PLATFORM_RULES: dict[str, str] = {
    "bluesky": "max 300 characters, one idea, a plain link at the end, no hashtags spam (max 2).",
    "mastodon": "max 500 characters, conversational, up to 3 hashtags, link at the end, add alt text for images.",
    "x": "max 280 characters including the link (count a link as 23). Hook first. No hashtags unless essential.",
    "threads": "max 500 characters, friendly, no hashtags, link at the end.",
    "linkedin": "up to 1300 characters, short lines, a concrete lesson, finish with a question; no hashtag walls (max 3).",
    "facebook": "2-4 short paragraphs, conversational, link in the text.",
    "instagram": "caption up to 2200 characters, first line is the hook, line breaks, 5-10 relevant hashtags at the end.",
    "reddit": "a genuinely useful self-post with a clear title; no marketing tone; disclose that it is our own guide; follow subreddit etiquette.",
    "telegram": "up to 1000 characters, informative, link at the end.",
    "pinterest": "title up to 100 characters, description up to 500, keyword rich, link to the guide.",
    "tiktok": "caption up to 150 characters plus 3-5 hashtags.",
    "youtube": "title up to 70 characters, description 2-4 paragraphs with the guide link in the first line, 10-15 tags.",
    "article": "600-1500 words of Markdown with H2 sections, a short intro, a verification note (what was checked, when), and a canonical link back to the guide.",
}


class Writer(Agent):
    role = "senior copywriter"
    temperature = 0.7

    def post(self, platform: str, topic: str, angle: str, link: str = "", facts: str = "", with_image: bool = False) -> dict[str, Any]:
        rules = PLATFORM_RULES.get(platform, "short, specific, useful.")
        memory = self.memory_context(topic)
        data = self.ask_json(
            f"Write one {platform} post.\nTopic: {topic}\nAngle: {angle}\nLink to include: {link or '(none)'}\n"
            f"Verified facts you may use (and only these): {facts or '(none supplied: use no numbers or claims that need checking)'}\n"
            f"Platform rules: {rules}\nRelated things we published before (do not repeat them): {memory}\n"
            + ("Also write an alt text for the accompanying image.\n" if with_image else "")
            + 'Return JSON: {"text": "...", "title": "...", "tags": ["..."], "alt_text": "...", "image_prompt": "a short visual brief for an illustrator, no text in the image unless stated"}'
        )
        data.setdefault("tags", [])
        data.setdefault("title", topic)
        return data

    def article(self, topic: str, angle: str, link: str = "", facts: str = "", platform: str = "devto") -> dict[str, Any]:
        data = self.ask_json(
            f"Write a full article for {platform}.\nTopic: {topic}\nAngle: {angle}\nCanonical guide URL: {link or '(none)'}\n"
            f"Verified facts (only these): {facts or '(none: keep claims generic and mark anything that needs checking in [brackets])'}\n"
            f"Rules: {PLATFORM_RULES['article']}\n"
            'Return JSON: {"title": "...", "markdown": "...", "excerpt": "one sentence", "tags": ["..."], "cover_prompt": "visual brief for the cover image"}',
            temperature=0.6,
        )
        data.setdefault("tags", [])
        return data

    def video_script(self, topic: str, angle: str, target_seconds: int, link: str = "", facts: str = "", presenter: bool = False) -> dict[str, Any]:
        n_scenes = max(4, min(40, target_seconds // 9))
        return self.ask_json(
            f"Write the script for a YouTube video of about {target_seconds} seconds ({target_seconds//60} min {target_seconds%60} s).\n"
            f"Topic: {topic}\nAngle: {angle}\nGuide URL for the description: {link or '(none)'}\n"
            f"Verified facts (only these): {facts or '(none: no numbers; put anything that needs checking in [brackets])'}\n"
            f"Structure: a 10-second hook, then {n_scenes} scenes of 6-12 seconds each, then a one-line close with a reason to open the guide. "
            f"Narration is spoken English at ~155 words per minute: write about 2.5 words per second of scene length. "
            f"Each scene needs a visual_prompt for an image/video model: concrete, photographic or clean-illustration style, no on-screen text, no logos, no faces of real people. "
            + ("Mark 2-3 scenes as mode 'presenter' where a host talks to camera. " if presenter else "")
            + "Mode is one of: generated (short cinematic motion clip), image_motion (still with slow camera move), presenter.\n"
            'Return JSON: {"title": "...", "description": "...", "tags": ["..."], "music_prompt": "...", '
            '"scenes": [{"narration": "...", "visual_prompt": "...", "mode": "image_motion", "seconds": 8, "on_screen_text": ""}]}',
            temperature=0.6,
        )

    def captions_for_short(self, title: str, platform: str) -> dict[str, Any]:
        return self.ask_json(
            f"Write the caption for a vertical short cut from the video '{title}' for {platform}. Rules: {PLATFORM_RULES.get(platform, 'short')}\n"
            'Return JSON: {"text": "...", "title": "...", "tags": ["..."]}'
        )

    def reply(self, platform: str, our_post: str, comment_author: str, comment: str) -> dict[str, Any]:
        return self.ask_json(
            f"A reader commented on our {platform} post.\nOur post: {our_post[:800]}\n{comment_author} wrote: {comment[:800]}\n"
            "Write a helpful, warm, specific reply in one to three sentences. Answer the question if there is one; if you do not know, say so and offer to check. "
            "No links unless the reader asks where the guide is. Never argue. If the comment is spam, abuse or off-topic, set skip=true.\n"
            'Return JSON: {"text": "...", "skip": false, "reason": ""}',
            temperature=0.5,
        )

    def revise(self, kind: str, draft: dict[str, Any], critique: str) -> dict[str, Any]:
        return self.ask_json(
            f"Revise this {kind} following the editor's notes exactly. Keep the same JSON keys.\nDraft: {draft}\nEditor notes: {critique}",
            temperature=0.5,
        )
