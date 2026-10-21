---
label: X
kinds: [post, thread, image]
char_limit: 280
hashtags_max: 1
link_policy: penalized
ai_label: recommended
ai_label_text: ""
media: {image: "1600x900 or 1080x1080, up to 4", video: "up to 2:20 for non-Premium, 1280x720 or 1080x1920"}
cadence: {per_day: 2, best_hours_utc: [13, 16, 20]}
publish: browser-or-intent (API is pay-per-post since Feb 2026)
last_checked: 2026-10-20
sources:
  - https://www.socialpilot.co/blog/twitter-algorithm
  - https://adlibrary.com/guides/x-twitter-algorithm-explained
  - https://opentweet.io/blog/x-algorithm-open-source-github-2026
  - https://www.wearefounders.uk/the-x-api-price-hike-a-blow-to-indie-hackers/
---

## How the feed ranks (2026)
- For You is scored per post; replies are the strongest positive signal, ahead of reposts, likes and dwell time. A reply that the author answers is weighted far above a plain reply (reported from the open-sourced code; exact weights vary by analysis).
- Early engagement in the first 30-60 minutes decides most of a post's reach.
- Outbound links are suppressed in For You: since March 2026 non-Premium accounts posting links see near-zero algorithmic distribution. Followers still see them.
- Premium gives a modest ranking advantage; it is one input, not a multiplier.
- Reply downvotes (Premium users) shape reply ordering since March 2026.
- Media posts (image, native video) outperform plain text; native video is favoured over links to video.

## Rules that bite
- Automation outside the API is against the rules; the agency only pre-fills a post in your browser and you click Publish. No bulk actions, no auto-follow, no auto-replies.
- Hashtags barely help on X; one at most, or none. Hashtag walls look like spam.
- No engagement bait ("like if…", "RT to win"). Repeated identical posts are throttled.

## What works for us
- Lead with the verified finding, not the topic. One claim per post. Numbers only from the guide's facts.
- Put the link in a reply to the post (first reply), never in the body, unless the account is Premium.
- Threads: 3-6 posts, each standalone, first post is the hook, last post is the guide link + "what we checked".
- Ask a real question people can answer in one line: replies are the currency.
- Post when the US and Europe overlap (13:00-16:00 UTC) and at 20:00 UTC for the US evening.

## Don'ts
- No "best", "#1", "guaranteed". No outrage bait. No posting the same guide more than once a week.
- No hashtags in the middle of sentences. No more than one link per thread.

## Updates
- 2026-10-20: card created from current reporting; link suppression and reply-downvote behaviour are reported by marketing analyses of the open-sourced code, not confirmed numbers.
