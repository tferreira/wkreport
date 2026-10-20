import json
import os
from datetime import datetime
from statistics import median
from typing import Any

import click
import requests
from bs4 import BeautifulSoup


class WaniKaniScraper():
    def __init__(self, username: str, token: str):
        self.username = username
        self.token = token

    def fetch_profile(self) -> dict[str, Any]:
        """Fetches the HTML code of the public profile"""
        url = f"https://production-sfo.browserless.io/content?token={self.token}"
        headers = {
            "Cache-Control": "no-cache",
            "Content-Type": "application/json"
        }
        data = {
            "url": f"https://www.wanikani.com/users/{self.username}"
        }
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        resp.raise_for_status()
        return resp.text

    def get_stats(self) -> dict[str, Any]:
        """Extracts stats from the HTML page"""
        profile_html = self.fetch_profile()
        soup = BeautifulSoup(profile_html, "html.parser")

        def parse_number(value: str) -> int:
            cleaned = value.strip().replace(",", "")
            try:
                return int(cleaned)
            except ValueError as err:
                raise ValueError(f"Could not parse integer from {value!r}") from err

        # Basic stats
        serving_since_element = soup.find("span", {"class": "public-profile__serving-since-date"})
        if not serving_since_element:
            raise ValueError("Could not locate serving since date on profile page")
        serving_since_time = serving_since_element.find("time")
        if not serving_since_time or "datetime" not in serving_since_time.attrs:
            raise ValueError("Serving since time element is missing required attributes")
        service_since_str = serving_since_time["datetime"]
        username_element = soup.find("div", {"class": "public-profile__username"})
        level_element = soup.find("div", {"class": "public-profile__level-info-level"})
        stage_element = soup.find("div", {"class": "public-profile__level-info-stage"})
        if not username_element or not level_element or not stage_element:
            raise ValueError("Could not locate basic user information on profile page")

        stats: dict[str, Any] = {
            "username": username_element.get_text(strip=True),
            "level": level_element.get_text(strip=True),
            "stage": stage_element.get_text(strip=True),
            "serving_since": datetime.strptime(service_since_str, "%Y-%m-%dT%H:%M:%SZ"),
        }

        stats["srs-stages"] = {}
        subject_labels = [
            ("radical", "Radicals"),
            ("kanji", "Kanji"),
            ("vocabulary", "Vocabulary"),
        ]
        srs_section = soup.find("div", class_="public-profile__srs-progress")
        if not srs_section:
            raise ValueError("Could not locate SRS progress section on profile page")

        stage_rows = srs_section.find_all("a", class_="item-spread-table-row")
        if not stage_rows:
            raise ValueError("Could not locate any SRS stage rows on profile page")

        # Iterate over SRS progress stages
        for row in stage_rows:
            title_element = row.find("div", class_="item-spread-table-row__title")
            total_element = row.find("div", class_="item-spread-table-row__total")
            if not title_element or not total_element:
                continue

            stage_title = title_element.get_text(strip=True)
            stage_total = parse_number(total_element.get_text())

            subjects: dict[str, Any] = {}
            for key, label in subject_labels:
                count_element = row.select_one(f".item-spread-table-row__count--{key}")
                if not count_element:
                    continue
                subjects[label] = {
                    "title": label,
                    "count": parse_number(count_element.get_text()),
                }

            stats["srs-stages"][stage_title] = {
                "title": stage_title,
                "total": stage_total,
                "subjects": subjects,
            }

        stats["progress"] = {}
        # Kanji progress
        kanji_progress = soup.find("div", {"class": "public-profile__kanji-progress"})
        if not kanji_progress:
            raise ValueError("Could not locate kanji progress section on profile page")
        kanji_percent_element = kanji_progress.find("div", {"class": "progress-chart__progress-bar-label-count"})
        max_kanji_element = kanji_progress.find("div", {"class": "progress-chart__bar-axis-max"})
        if not kanji_percent_element or not max_kanji_element:
            raise ValueError("Kanji progress section is missing required data")
        kanji_percent = kanji_percent_element.get_text(strip=True)
        max_kanjis = parse_number(max_kanji_element.get_text())
        known_kanjis = sum(
            stage_data["subjects"].get("Kanji", {}).get("count", 0)
            for stage_title, stage_data in stats["srs-stages"].items()
            if stage_title != "Apprentice"
        )
        stats["progress"]["kanji"] = {
            "known": known_kanjis,
            "max": max_kanjis,
            "percent": kanji_percent
        }

        # Vocabulary progress
        vocab_progress = soup.find("div", {"class": "public-profile__vocabulary-progress"})
        if not vocab_progress:
            raise ValueError("Could not locate vocabulary progress section on profile page")
        vocab_percent_element = vocab_progress.find("div", {"class": "progress-chart__progress-bar-label-count"})
        max_vocab_element = vocab_progress.find("div", {"class": "progress-chart__bar-axis-max"})
        if not vocab_percent_element or not max_vocab_element:
            raise ValueError("Vocabulary progress section is missing required data")
        vocab_percent = vocab_percent_element.get_text(strip=True)
        max_vocab = parse_number(max_vocab_element.get_text())
        known_vocab = sum(
            stage_data["subjects"].get("Vocabulary", {}).get("count", 0)
            for stage_title, stage_data in stats["srs-stages"].items()
            if stage_title != "Apprentice"
        )
        stats["progress"]["vocabulary"] = {
            "known": known_vocab,
            "max": max_vocab,
            "percent": vocab_percent
        }

        return stats


class WaniKaniAPI():
    """Minimal WaniKani API v2 client for the cheap, single-call stats.

    Only endpoints that cost one request are used here. Lifetime stats like
    review accuracy or JLPT coverage would need to page through thousands of
    records on every run, so they are deliberately left out.
    """

    BASE = "https://api.wanikani.com/v2"

    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path: str) -> dict[str, Any]:
        resp = requests.get(f"{self.BASE}{path}", headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _parse_ts(value: str) -> datetime:
        # WaniKani timestamps are ISO-8601 with a trailing Z and variable
        # fractional seconds; fromisoformat handles both once Z is normalised.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def review_forecast(self) -> dict[str, int]:
        """Reviews waiting now and coming up in the next 24h (1 API call)."""
        buckets = self._get("/summary")["data"].get("reviews", [])
        now = len(buckets[0]["subject_ids"]) if buckets else 0
        next_24h = sum(len(b["subject_ids"]) for b in buckets)
        return {"now": now, "next_24h": next_24h}

    def velocity(self, recent: int = 10) -> dict[str, Any]:
        """Typical days per level and projection to level 60 (1 API call).

        Uses the median of the most recent passed levels, so a one-off hiatus
        (e.g. a 700-day gap on an early level) doesn't skew the estimate the
        way a plain mean would.
        """
        progressions = self._get("/level_progressions")["data"]
        durations = []
        current_level = 0
        for item in progressions:
            data = item["data"]
            current_level = max(current_level, data["level"])
            if data.get("started_at") and data.get("passed_at"):
                delta = self._parse_ts(data["passed_at"]) - self._parse_ts(data["started_at"])
                durations.append((data["level"], delta.total_seconds() / 86400))
        durations.sort()
        recent_days = [days for _, days in durations[-recent:]]
        days_per_level = median(recent_days) if recent_days else 0.0
        remaining = max(0, 60 - current_level)
        return {"days_per_level": days_per_level, "to_60_days": days_per_level * remaining}

    def review_stats(self) -> dict[str, Any]:
        """Lifetime accuracy (overall + per subject type) and critical count.

        Pages through all review statistics — one record per subject reviewed,
        so a handful of calls. Aggregated per page so the full list is never
        held in memory. "Critical" = an active item answered correctly < 75% of
        the time (WaniKani's "critical condition" threshold).
        """
        correct = incorrect = 0
        by_type: dict[str, list[int]] = {}
        critical = 0
        url = f"{self.BASE}/review_statistics"
        while url:
            resp = requests.get(url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            page = resp.json()
            for item in page["data"]:
                data = item["data"]
                right = data["meaning_correct"] + data["reading_correct"]
                wrong = data["meaning_incorrect"] + data["reading_incorrect"]
                correct += right
                incorrect += wrong
                tally = by_type.setdefault(data["subject_type"], [0, 0])
                tally[0] += right
                tally[1] += wrong
                if not data["hidden"] and data["percentage_correct"] < 75:
                    critical += 1
            url = page["pages"]["next_url"]
        total = correct + incorrect
        overall = 100 * correct / total if total else 0.0
        per_type = {t: 100 * c / (c + w) for t, (c, w) in by_type.items() if c + w}
        return {"overall": overall, "per_type": per_type, "critical": critical}


JLPT_LEVELS = ["N5", "N4", "N3", "N2", "N1"]
JLPT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jlpt_kanji.json")


def jlpt_coverage(current_level: int, cumulative: bool = True) -> list[tuple[str, float]]:
    """JLPT kanji coverage by the WaniKani curriculum at ``current_level``.

    Mirrors wkstats: a JLPT kanji counts as covered once WaniKani introduces it
    (its ``wk_level <= current_level``). This is curriculum coverage, not SRS /
    "learned" progress, so it needs no API call — only the bundled kanji list
    (character -> wk_level, null when the kanji isn't in WaniKani) and the level.
    """
    with open(JLPT_DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    run_cov = run_tot = 0
    result = []
    for level in JLPT_LEVELS:
        kanji = data[level]  # {character: wk_level or null}
        covered = sum(1 for wk in kanji.values() if wk is not None and wk <= current_level)
        if cumulative:
            run_cov += covered
            run_tot += len(kanji)
            pct = 100 * run_cov / run_tot if run_tot else 0.0
        else:
            pct = 100 * covered / len(kanji) if kanji else 0.0
        result.append((level, pct))
    return result


@click.command()
@click.option("--username", help="Wanikani username", required=True)
@click.option("--webhook-url", help="Mattermost webhook URL")
@click.option("--token", help="Browserless Token")
@click.option("--wk-token", help="WaniKani API v2 token (adds review forecast + level-up velocity)")
def run(username, webhook_url, token, wk_token):
    """Parses a public WaniKani profile and sends a report to Mattermost"""
    # Parse website
    scraper = WaniKaniScraper(username, token)
    stats = scraper.get_stats()

    # API stats (only if a WaniKani token is supplied). Forecast and velocity
    # are one call each; review_stats pages through all review statistics (a
    # handful of calls) for accuracy and the critical-item count.
    api_lines = []
    if wk_token:
        api = WaniKaniAPI(wk_token)
        forecast = api.review_forecast()
        vel = api.velocity()
        reviews = api.review_stats()
        per_type = reviews["per_type"]
        accuracy = f'Accuracy    {reviews["overall"]:.0f}% overall'
        if "kanji" in per_type:
            accuracy += f' · kanji {per_type["kanji"]:.0f}%'
        if "vocabulary" in per_type:
            accuracy += f' · vocab {per_type["vocabulary"]:.0f}%'
        api_lines = [
            f'Reviews     {forecast["now"]} now · {forecast["next_24h"]} in next 24h',
            f'Velocity    {vel["days_per_level"]:.0f} days/level · ~{vel["to_60_days"] / 365:.1f} yrs to level 60',
            accuracy,
        ]
        if reviews["critical"]:
            api_lines.append(f'Critical    {reviews["critical"]} items under 75% accuracy')

    # Generate report. No `####` heading: the "Crabigator" bot name already
    # titles the post, so a second bold heading just reads as a duplicate title.
    # The user/stage/level go on a normal lead line instead.
    kanji = stats["progress"]["kanji"]
    vocab = stats["progress"]["vocabulary"]
    lead = f'**{stats["username"]}** · {stats["stage"]} {stats["level"]}'

    def bar(known: int, maximum: int, width: int = 24) -> str:
        """Draws a monospace progress bar; renders the same on desktop/mobile."""
        filled = round((known / maximum) * width) if maximum else 0
        filled = max(0, min(width, filled))
        return "█" * filled + "░" * (width - filled)

    progress_lines = [
        f'Kanji       {bar(kanji["known"], kanji["max"])} {kanji["percent"]:>4}  {kanji["known"]}/{kanji["max"]}',
        f'Vocabulary  {bar(vocab["known"], vocab["max"])} {vocab["percent"]:>4}  {vocab["known"]}/{vocab["max"]}',
    ]

    # Cumulative JLPT coverage for the current level (needs no API call).
    level_digits = "".join(ch for ch in stats["level"] if ch.isdigit())
    if level_digits:
        coverage = jlpt_coverage(int(level_digits), cumulative=True)
        progress_lines.append(
            "JLPT (cum)  " + "  ".join(f"{lv} {pct:.1f}%" for lv, pct in coverage)
        )

    # Render the stage/subject breakdown as a fixed-width table inside a code
    # block. The Mattermost mobile app doesn't render markdown tables (it shows
    # the raw pipes, as on desktop it renders them), but it does render fenced
    # code blocks in a monospace font, so an aligned ASCII table keeps the same
    # layout on both. Emoji would break the monospace alignment, so the stage
    # names are used plain as headers (and the emoji legend is dropped).
    stages = list(stats["srs-stages"].keys())

    # Build the grid: a label column, then one column per stage.
    rows = [[""] + stages]
    for subject in ("Radicals", "Kanji", "Vocabulary"):
        row = [subject]
        for stage in stages:
            count = stats["srs-stages"][stage]["subjects"].get(subject, {}).get("count", 0)
            row.append(str(count))
        rows.append(row)
    rows.append(["Total"] + [str(stats["srs-stages"][s]["total"]) for s in stages])

    # Right-align the numeric columns to the widest value in each.
    widths = [max(len(row[c]) for row in rows) for c in range(len(rows[0]))]
    table_lines = []
    for row in rows:
        cells = [row[0].ljust(widths[0])]
        cells += [row[c].rjust(widths[c]) for c in range(1, len(row))]
        table_lines.append("  ".join(cells).rstrip())
    # One code block: progress bars (+ optional API stats), blank line, grid.
    block = "```\n" + "\n".join(progress_lines + api_lines + [""] + table_lines) + "\n```"

    params = {
        "username": "Crabigator",
        "icon_url": "https://global.discourse-cdn.com/wanikanicommunity/original/4X/6/2/a/62a8b0f4c59ff2c5b6651ffcf43531480b3e5297.png",
        "text": "\n\n".join([lead, block]),
    }
    resp = requests.post(url=webhook_url, json=params, timeout=10)
    resp.raise_for_status()

if __name__ == '__main__':
    run()
