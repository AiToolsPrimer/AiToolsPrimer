# AI Tools Primer Agency

A marketing agency that runs on one Mac, with no API tokens and nothing to pay for.
A **director** model plans and reviews; specialist **agents** research, write, verify,
illustrate, film, voice, score, publish and learn; an **office** dashboard shows every
agent at work in real time, with the switches, the approval queue and the logs.
Everything produced is in English. Everything that leaves the Mac goes through official
APIs, or through the agent's own Chrome with your click.

Target machine: **Mac mini M5 Pro, 64 GB, one model in memory at a time.** Every model was
chosen against independent leaderboards with two hard filters: it runs on Apple Silicon,
and its licence allows commercial use. Evidence: [docs/MODELS.md](docs/MODELS.md).

## The brain and the team

| Role | Model | Precision |
|---|---|---|
| Brain (director, strategist, writer, judge, fact checker, vision) | Qwen3.8-Flash-Next, 125B MoE, 6B active | ~4-bit, n-gram table on the SSD |
| Second pen and automatic fallback | Qwen3.8-27B | 8-bit |
| Images | Qwen-Image-2512 | 8-bit (mflux) |
| Image editing | Qwen-Image-Edit-2511 | GGUF Q8 (ComfyUI) |
| Video, up to 4 minutes | LTX-2.5 | bf16 (MLX) |
| Presenter | LTX MLX audio-to-video | |
| Voice | Step-Audio-EditX (Kokoro, Chatterbox fallback) | int8 |
| Transcription | Parakeet TDT 0.6B v2 | |
| Music | ACE-Step 1.5 | |
| Memory | Qwen3-Embedding-8B | |
| Safety | Qwen3Guard-Gen-4B | |

`agency doctor --benchmark` loads each brain candidate once on your Mac and keeps the
strongest one that runs well; the 27B takes over automatically if Flash-Next ever fails.
Two models draft every piece, the brain judges and merges (`models.team_mode`).

## What it does, every day

- **Research**: reads the site, scans Hacker News, Reddit and Google Trends, proposes angles tied to your guides; new site pages are pushed to IndexNow.
- **Plan**: the day's items (or the monthly editorial plan when one exists).
- **Write**: posts, threads, carousels, articles, scripts, captions, per the platform's knowledge card.
- **Verify, sentence by sentence**: every sentence is checked against the facts extracted from the guide it links to; unsupported claims, numbers not in the facts and promise words without a fact are removed. Non-English text is rejected.
- **Limits enforced by code**: character limits, hashtag caps, link placement (first comment on LinkedIn), AI labels.
- **Illustrate and film**: images with a vision check; videos assembled scene by scene (generated clips or stills with camera motion, voice, ducked music, subtitles), vertical shorts cut from each.
- **Safety, policy, queue**: brand rules, the guard model, your switches, rate limits, quiet hours, then the approval queue.
- **Publish**: through the official API, or in the agent's Chrome with your click, or as a one-tap intent link, or as a copy-ready package, per platform.
- **Community**: comments under our posts answered (your switch), comments on followed sources drafted and sent only after your approval, one at a time, capped per day.
- **Outreach**: inbox read (read-only) and sorted, journalist requests pulled from the digests, replies and pitches drafted into Gmail Drafts; unlinked mentions and dead links on authoritative sites only (Tranco rank), with pitches.
- **Learn**: metrics through the official APIs, lessons every evening, cadence adjusted, your corrections distilled into house style rules every Sunday, a training set for a LoRA fine-tune when there are enough pairs.
- **Deliver**: monthly editorial plan, monthly report, campaign presentations, in PDF; a morning briefing (spoken if you like).
- **Keep itself current**: a weekly news watch proposes updates to the platform cards; you apply them with a click.

## What it refuses to do, by design

- **Pay for anything.** Every outbound request passes a guard that blocks payment processors, ads and boost endpoints, checkout, billing, subscription URLs and any body carrying a card number, CVV, IBAN or wallet address. X's API is pay-per-post, so X is browser-with-your-click only.
- **Create accounts.** The scout finds platforms and prepares the kit (handle, bios, avatar, banner, first posts); you click "sign up".
- **Mass actions.** No automated follows or friend requests, no comments on other people's content without your click, never in bulk, never through a CAPTCHA.

These are hard guarantees: the dashboard shows them and nothing switches them off.

## Platforms (26)

API: Bluesky, Mastodon, YouTube, Reddit (manual by rule), Telegram, Facebook Page, Instagram, Threads, LinkedIn, TikTok, Pinterest, WordPress, DEV, Hashnode, Tumblr, Vimeo.
Browser with your click: X, Medium, Substack, LinkedIn Articles, Blogger, Dailymotion.
One tap: Flipboard. Drafts or fact cards only: Quora, Hacker News, Stack Exchange.
Plus a podcast feed (articles read by the local voice) and IndexNow for the search engines.

## Install (Mac)

```bash
git clone <this repo> && cd AiToolsPrimer/agency
scripts/install_mac.sh          # brew, python env, LM Studio, llama.cpp, Chrome, MLX packages, ComfyUI, ACE-Step, Agency.app
scripts/download_models.sh      # about 130 GB
.venv/bin/agency doctor --benchmark
.venv/bin/agency chrome-login x medium substack   # log in once in the agent's Chrome
cp .env.example .env            # fill in the platforms you use
.venv/bin/agency run            # dashboard at http://127.0.0.1:8765 (or click Agency.app)
```

`config/agency.yaml` starts with `dry_run: true`: everything runs and files are produced, but
every connector only simulates. Set it to `false` when the queue looks right. Defaults keep
`publishing` off and `approval_required` on: nothing leaves without your click until you decide.

## The office (dashboard)

Office (every desk live, phase, model in memory, feed, switches, run buttons) · Queue (approve, edit,
reject; edits become corrections) · Operator (browser tasks with screenshots, Publish / Cancel) ·
Outreach (network, questions, inbox, PR) · Deliverables (plan, report, campaign, briefing) · Content
(pipeline per item: team, fact check, limits, safety, policy, result) · Assets · Platforms (on/off and
mode per platform) · Knowledge (cards, proposed updates) · Learning (corrections, style rules, training
set) · Models (benchmark, lineup, loads) · Scout · Logs.

## Command line

```bash
agency cycle --dry-run          # one full day now
agency video --topic "..." --seconds 240
agency post --platform bluesky --topic "..." --image
agency queue / agency approve 12 / agency toggle publishing on
agency doctor [--benchmark] / agency chrome-login x
```

## Tests

```bash
pip install -e ".[dev]" playwright && pytest
```

103 tests rehearse the whole agency in dry-run mode with a fake model: the fact checker, the
team, the policy engine and the payment guard, all 26 connectors, the browser operator against a
local compose page (a real Chromium), a real FFmpeg assembly of a video with shorts, the podcast feed,
the knowledge base, outreach, deliverables (PDF through Chromium) and every dashboard page.

What is not verified here: the local model runtimes themselves (LM Studio, llama.cpp with
Flash-Next, mflux, LTX-2.5 on MLX, Step-Audio-EditX, ACE-Step) need the Mac; `agency doctor`
reports what is missing and the install script names the packages to check.
