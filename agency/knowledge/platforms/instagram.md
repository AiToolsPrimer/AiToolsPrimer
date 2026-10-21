---
label: Instagram
kinds: [image, carousel, reel]
char_limit: 2200
hashtags_max: 5
link_policy: not-clickable
ai_label: required-for-realistic-ai
ai_label_text: ""
media: {image: "1080x1350 (4:5) preferred, 1080x1080 ok", carousel: "up to 20 slides, 1080x1350", reel: "1080x1920, 15-90 s best, up to 3 minutes", cover: "1080x1920 with safe zone"}
cadence: {per_day: 1, per_week: 5, best_hours_utc: [11, 14, 19]}
publish: api (Business/Creator account, media from a public URL)
last_checked: 2026-10-20
sources:
  - https://later.com/blog/ultimate-guide-to-using-instagram-hashtags/
  - https://creatorlanehq.com/blog/instagram-5-hashtag-limit-2026
  - https://www.usefastlane.ai/blog/instagram-reels-algorithm-2026
  - https://developers.facebook.com/docs/instagram-platform/content-publishing
---

## How ranking works (2026)
- Hashtags are capped at 5 per post or Reel since December 2025; extra tags are ignored. They are topic metadata, not a reach engine.
- Reels: watch completion, shares (sends) and saves are the strong signals; likes are weak. The first 1-2 seconds decide retention.
- Originality rules (expanded 30 April 2026) apply to photos and carousels too: accounts that mostly repost are not recommended to non-followers; watermarked reposts are demoted.
- Carousels get a second chance in the feed (slide 2 is shown to people who skipped) and drive saves.
- Captions: the first line is the hook (what shows before "more"). Keywords in captions and alt text feed search.
- Links in captions are not clickable: use "link in bio" (or a link sticker in Stories).

## Rules
- Realistic AI-generated people or scenes require the AI label; an account-level "AI creator" label is being tested for accounts that regularly post AI content (reported from May 2026). Label honestly.
- Media for the API must be reachable from a public URL (PUBLIC_MEDIA_BASE_URL).
- No engagement bait, no follow/unfollow games, no pods.

## What works for us
- Carousels: "5 tools compared" with one tool per slide, big legible text (Qwen-Image renders text well), last slide "full table on the guide (link in bio)".
- Reels: 30-45 s cuts from the long video with burned captions and a text hook in the first frame.
- Alt text with keywords. Five precise hashtags (pillar + topic + format).

## Updates
- 2026-10-20: card created; 5-hashtag limit confirmed by multiple reports; AI creator label deadline unverified.
