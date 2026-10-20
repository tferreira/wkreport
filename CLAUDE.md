# CLAUDE.md

Guidance for working on this repo.

## What it does

`run.py` scrapes a public WaniKani profile (via browserless) and posts a
progress report to a Mattermost incoming webhook. Extra stats from the WaniKani
API are added when `--wk-token` is supplied. See `README.md` for usage.

## Non-obvious constraints — don't regress these

- **The report body must stay inside a fenced code block.** The Mattermost
  *mobile* app does NOT render Markdown tables — it prints the raw `|` pipes.
  Do not "improve" the layout into a Markdown table; it will look fine on
  desktop and broken on phones.
- **No emoji inside the code block.** Emoji aren't single-width, so they break
  the monospace column alignment. Stage headers are plain words on purpose
  (an emoji legend was tried and removed).
- **JLPT coverage is curriculum-based, not SRS-based.** A kanji counts as
  covered once its `wk_level <= your current level` (this matches wkstats). It
  needs no API call — only `jlpt_kanji.json` and the scraped level.
- **Velocity uses the median of recent levels, not the mean**, so a long early
  hiatus (e.g. a ~700-day Level 1) doesn't skew the estimate.

## Costs

With `--wk-token` a run makes ~7 API calls: forecast (1), velocity (1),
review_statistics (~5, paginated). JLPT coverage and the profile scrape add
no API calls.

## Testing the formatting without secrets

Only the scrape and the webhook POST need secrets. To exercise the layout,
stub `WaniKaniScraper.get_stats` to return canned stats and monkeypatch
`requests.post` to capture the payload instead of sending it.
