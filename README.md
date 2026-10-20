# wkreport

Posts a WaniKani progress report to Mattermost, formatted to render correctly
on **both the desktop and mobile** Mattermost apps.

Basic stats are scraped from your public WaniKani profile (rendered through
[browserless] so the page's JavaScript runs). Optional extra stats — review
forecast, level-up velocity, accuracy — are pulled from the WaniKani API when
you supply a token.

## What's in the report

- **Progress bars** for kanji and vocabulary.
- **JLPT coverage** (cumulative) — how much of each JLPT level WaniKani has
  taught you by your current level. Needs no token.
- **SRS stage grid** — radicals / kanji / vocabulary per stage
  (Apprentice → Burned).
- With `--wk-token`, also: **review forecast**, **level-up velocity**, and
  **lifetime accuracy** (plus a critical-items line when any item is < 75%).

The whole body is rendered inside a fenced code block so the monospace layout
survives the Mattermost **mobile** app, which does not render Markdown tables.

## Install

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt
```

## Usage

```bash
venv/bin/python run.py \
  --username   <wanikani-username> \
  --webhook-url <mattermost-incoming-webhook-url> \
  --token      <browserless-token> \
  --wk-token   <wanikani-api-token>      # optional
```

| Option | Needed | What it is |
| --- | --- | --- |
| `--username` | yes | Your public WaniKani username |
| `--webhook-url` | to post | Mattermost incoming webhook URL |
| `--token` | to scrape | [browserless] API token (renders the JS profile page) |
| `--wk-token` | no | WaniKani API v2 token; adds forecast, velocity, accuracy |

Without `--wk-token` you still get the progress bars, JLPT coverage and the
stage grid — those don't call the API.

### Getting the tokens

- **Mattermost webhook** — a channel's *Integrations → Incoming Webhooks*.
- **browserless** — an API token from [browserless.io][browserless].
- **WaniKani API** — *wanikani.com → Settings → API Tokens* (read-only is fine).

## JLPT data

`jlpt_kanji.json` maps each JLPT kanji to its WaniKani level and is derived from
[davidluzgouveia/kanji-data] (MIT, © 2019 David Gouveia). There is no official
JLPT kanji list, so coverage numbers are close to — but not identical to —
other tools such as wkstats.

[browserless]: https://www.browserless.io/
[davidluzgouveia/kanji-data]: https://github.com/davidluzgouveia/kanji-data
