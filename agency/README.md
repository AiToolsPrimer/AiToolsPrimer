# AI Tools Primer Agency

A marketing agency that runs on one Mac, with no API tokens and nothing to pay for.
A **director** model plans and reviews; specialist **agents** research, write, illustrate,
film, voice, score, publish and learn; a **control panel** gives you the switches,
the approval queue and the logs. Everything is produced in English.

Target machine: **Mac mini M5 Pro, 64 GB**. Every model was picked against independent
leaderboards with two hard filters: it runs on Apple Silicon, and its licence allows
commercial use. The evidence is in [docs/MODELS.md](docs/MODELS.md).

## What it does

| Agent | Job | Model |
|---|---|---|
| Director | reads the strategist, plans the day, commissions work, reviews drafts, decides what goes out | Qwen3.8-27B |
| Strategist | inventories the site, scans free trend sources (HN, Reddit, Google Trends), proposes angles | Qwen3.8-27B |
| Writer | posts, threads, articles, captions, video scripts, replies, per-platform rules | Qwen3.8-27B |
| Art director | illustrations, covers, thumbnails, avatars; vision QA on every picture | Qwen-Image-2512 + Qwen3-VL-8B |
| Video producer | videos **up to 4 minutes**: script → scenes → clips/stills → voice → music → subtitles → master + vertical shorts | LTX-2.5, Chatterbox, ACE-Step 1.5, Parakeet |
| Community manager | reads comments under *our* posts and answers them | Qwen3.8-27B |
| Scout | finds new free platforms worth a presence and prepares a sign-up kit (handle, bios, avatar, banner, first posts) | Qwen3.8-27B |
| Analyst | pulls our metrics through the official APIs, writes what worked | Qwen3.8-27B |
| Safety | brand rules + Qwen3Guard before anything leaves | Qwen3Guard-Gen-4B |

Publishing goes through official APIs only, to accounts you connect with your own keys:
Bluesky, Mastodon, X, YouTube, Reddit, Telegram, Facebook Page, Instagram, Threads,
LinkedIn, TikTok, Pinterest, WordPress, DEV, Hashnode, Tumblr. Medium has no API any
more, so articles for it are prepared for a manual import.

## What it refuses to do, by design

- **Pay for anything.** Every outbound request passes a guard that blocks payment
  processors, ads/boost endpoints, checkout/billing/subscription URLs and any body
  carrying a card number, CVV, IBAN or wallet address. The log shows every block.
- **Create accounts.** The scout prepares everything; you click "sign up".
- **Mass actions.** No automated follows, friend requests or comments on other people's
  content. Those break every platform's terms and get accounts banned. Replies are
  only ever written under our own posts (and can be set to draft-only).

These three are hard guarantees: the panel shows them, nothing can switch them off.

## Switches (control panel)

`master_enabled` (kill switch) · `publishing` · `approval_required` · `write_posts` ·
`write_articles` · `make_images` · `make_videos` · `make_shorts` · `make_voiceover` ·
`make_music` · `auto_reply_own_posts` · `draft_external_engagement` ·
`discover_platforms` · `prepare_signup_kits` · `collect_metrics`, plus one switch per
platform. Defaults: everything produced lands in the approval queue; nothing is published
until you turn `publishing` on, and each item still needs your click until you turn
`approval_required` off.

## Install (Mac)

```bash
git clone <this repo> agency && cd agency
scripts/install_mac.sh        # brew, python env, LM Studio, ComfyUI, ACE-Step, MLX packages
scripts/download_models.sh    # ~90 GB
# start LM Studio's server (port 1234), ComfyUI (8188), ACE-Step (7867)
.venv/bin/agency doctor       # checks tools, servers, models, memory plan, platforms
cp .env.example .env          # fill in the platforms you use
.venv/bin/agency run          # panel at http://127.0.0.1:8765, scheduler on
```

`config/agency.yaml` starts with `dry_run: true`: the whole pipeline runs, files are
produced, but every connector only simulates. Set it to `false` when the queue looks right.

### ComfyUI workflows

Images, image edits and the presenter avatar run through ComfyUI. Export each workflow as
API JSON and drop it in `workflows/` with the tokens described in
[workflows/README.md](workflows/README.md). Video uses the LTX-2.5 MLX command by default
(faster on Apple Silicon); add `workflows/video.json` to route it through ComfyUI instead.

## Daily rhythm (UTC, configurable)

- 07:30 daily cycle: research → plan → produce → safety → queue/publish
- every 30 min: comments under our posts
- every 5 min: approved items whose scheduled time has come are released
- 22:00 analyst report → notes the director reads the next morning
- Monday 09:00 scout

## Command line

```bash
agency cycle --dry-run                      # one full day now
agency video --topic "Five free PDF editors tested" --seconds 240
agency post --platform bluesky --topic "..." --image
agency queue / agency approve 12
agency toggle publishing on / agency toggle list
```

## Memory plan (64 GB)

The director (17 GB) stays resident. Media models load one at a time: Qwen-Image-2512
(14 GB), LTX-2.5 (24 GB), voice and music (under 5 GB). `agency doctor` checks that the
director plus the heaviest media model fit the GPU budget. Raise macOS's GPU limit to
56 GB with `sudo sysctl iogpu.wired_limit_mb=57344`.

A four-minute video is 20-40 scenes. On an M5 Pro expect roughly 20-40 minutes of
rendering per video with mixed visuals (generated clips plus stills with camera motion),
longer if every scene is a generated clip. The agency runs it in the background and the
panel shows progress.

## Optional paid director

`director.provider: anthropic` in `agency.yaml` plus `ANTHROPIC_API_KEY` makes Claude the
director while every other agent stays local. It is off by default.

## Tests

```bash
pip install -e ".[dev]" && pytest
```

The suite rehearses the full pipeline in dry-run mode, including a real FFmpeg assembly of a
video with shorts, the payment guard, the policy engine, the platform connectors and the panel.
