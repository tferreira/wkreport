from datetime import datetime
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


@click.command()
@click.option("--username", help="Wanikani username", required=True)
@click.option("--webhook-url", help="Mattermost webhook URL")
@click.option("--token", help="Browserless Token")
def run(username, webhook_url, token):
    """Parses a public WaniKani profile and sends a report to Mattermost"""
    # Parse website
    scraper = WaniKaniScraper(username, token)
    stats = scraper.get_stats()

    # Generate report
    title = f'#### WaniKani Report for {stats["username"]} ({stats["stage"]} {stats["level"]})\n'
    kanji_progression = (
        f'Kanji Progression: '
        f'{stats["progress"]["kanji"]["known"]}/{stats["progress"]["kanji"]["max"]} '
        f'({stats["progress"]["kanji"]["percent"]})\n'
    )
    vocab_progression = (
        f'Vocabulary Progression: '
        f'{stats["progress"]["vocabulary"]["known"]}/{stats["progress"]["vocabulary"]["max"]} '
        f'({stats["progress"]["vocabulary"]["percent"]})\n\n'
    )

    # Build markdown table lines
    lines = ["|", "|", "|", "|"]  # stages, radicals, kanji, vocabulary
    for stage, stage_data in stats["srs-stages"].items():
        if stage == "Apprentice":
            emoji = ":egg:"
        if stage == "Guru":
            emoji = ":hatching_chick:"
        if stage == "Master":
            emoji = ":hatched_chick:"
        if stage == "Enlightened":
            emoji = ":mage:"
        if stage == "Burned":
            emoji = ":fire:"

        lines[0] += f'{stage} {emoji}|{stage_data["total"]}|'
        for i, (subject, subject_data) in enumerate(stage_data["subjects"].items(), start=1):
            lines[i] += f'{subject}|{subject_data["count"]}|'
    lines.insert(1, "|---|---|---|---|---|")

    params = {
        "username": "Crabigator",
        "icon_url": "https://global.discourse-cdn.com/wanikanicommunity/original/4X/6/2/a/62a8b0f4c59ff2c5b6651ffcf43531480b3e5297.png",
        "text": "\n".join([title, kanji_progression, vocab_progression] + lines)
    }
    requests.post(url=webhook_url, json=params)

if __name__ == '__main__':
    run()
