---
label: TikTok
kinds: [short, video]
char_limit: 2200
hashtags_max: 5
link_policy: none
ai_label: required-for-realistic-ai
ai_label_text: ""
media: {video: "1080x1920, 9:16, 21-45 s sweet spot, up to 10 minutes", cover: "first frame with text hook"}
cadence: {per_day: 1, per_week: 5, best_hours_utc: [12, 16, 20]}
publish: api (Direct Post needs an audited app; unaudited = private/SELF_ONLY or inbox drafts)
last_checked: 2026-10-20
sources:
  - https://blog.hootsuite.com/tiktok-algorithm/
  - https://storrito.com/resources/tiktoks-2026-ai-labeling-rules-and-what-they-signal-for-platform-governance/
  - https://www.outstand.so/blog/tiktok-content-posting-api
  - https://developers.tiktok.com/doc/content-posting-api-get-started
---

## How the For You feed ranks
- Watch time and completion rate first, then shares (especially sends to DMs), saves, rewatches, comments. Likes matter least. Finishing a longer video is a strong signal (TikTok's own statement).
- Each video is tested on a small audience; strong retention earns the next tier. Follower count matters little.
- Text on screen, captions and spoken keywords feed TikTok search; the first 3 words of the caption and the on-screen hook matter.

## Rules
- Realistic AI-generated visuals or audio must be labelled with TikTok's AI-generated label (toggle on upload; cannot be removed later). C2PA metadata is read automatically. Unlabelled realistic AI content can be down-ranked or removed; repeat cases risk the account.
- Content Posting API: until the app passes TikTok's audit, posts can only be private (SELF_ONLY) and the account must be private, or uploads go to the inbox as drafts. The agency uses inbox drafts until the audit passes.
- No links in captions (not clickable); link in bio only.

## What works for us
- Vertical cuts of the long video: hook in frame one ("We tested 5 free PDF editors. Two broke."), captions burned, 25-45 s, end with the question.
- Reply to comments with a short video when a question is common.
- Label AI visuals honestly; our presenter is declared as AI.

## Updates
- 2026-10-20: card created; ad disclosure rules updated July 2026 (ads only).
