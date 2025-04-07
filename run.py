from datetime import datetime
from typing import Any

import click
import requests
from bs4 import BeautifulSoup
from py_markdown_table.markdown_table import markdown_table


class WaniKaniScraper():
    def __init__(self, username: str):
        self.username = username

    def fetch_profile(self) -> dict[str, Any]:
        """Fetches the HTML code of the public profile"""
        url = f"https://www.wanikani.com/users/{self.username}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.text

    def get_stats(self) -> dict[str, Any]:
        """Extracts stats from the HTML page"""
        profile_html = self.fetch_profile()
        soup = BeautifulSoup(profile_html, "html.parser")

        # Basic stats
        serving_since_element = soup.find("span", {"class": "public-profile__serving-since-date"})
        service_since_str = serving_since_element.find("time")["datetime"]
        stats: dict[str, Any] = {
            "username": soup.find("div", {"class": "public-profile__username"}).text,
            "level": soup.find("div", {"class": "public-profile__level-info-level"}).text,
            "stage": soup.find("div", {"class": "public-profile__level-info-stage"}).text,
            "serving_since": datetime.strptime(service_since_str, "%Y-%m-%dT%H:%M:%SZ"),
        }

        stats["srs-stages"] = {}
        # Iterate over SRS progress stages
        for stage in soup.find_all("li", {"class": "srs-progress__stage"}):
            stage_title = stage.find("div", {"class": "srs-progress__stage-title"}).text
            stage_total = stage.find("div", {"class": "srs-progress__stage-total"}).text
            stats["srs-stages"][stage_title] = {
                "title": stage_title,
                "total": int(stage_total),
                "subjects": {},
            }
            # Fetch subject type details
            for sub_type in stage.find_all("div", {"class": "srs-progress__subject-type"}):
                sub_title = sub_type.find("div", {"class": "srs-progress__subject-type-title"}).text
                sub_count = sub_type.find("div", {"class": "srs-progress__subject-type-count"}).text
                stats["srs-stages"][stage_title]["subjects"][sub_title] = {
                    "title": sub_title,
                    "count": int(sub_count),
                }

        stats["progress"] = {}
        # Kanji progress
        kanji_progress = soup.find("div", {"class": "public-profile__kanji-progress"})
        kanji_percent = kanji_progress.find("div", {"class": "progress-chart__progress-bar-label-count"}).text
        max_kanjis = kanji_progress.find("div", {"class": "progress-chart__bar-axis-max"}).text
        known_kanjis = sum(
            stage_data["subjects"]["Kanji"]["count"]
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
        vocab_percent = vocab_progress.find("div", {"class": "progress-chart__progress-bar-label-count"}).text
        max_vocab = vocab_progress.find("div", {"class": "progress-chart__bar-axis-max"}).text
        known_vocab = sum(
            stage_data["subjects"]["Vocabulary"]["count"]
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
def run(username, webhook_url):
    """Parses a public WaniKani profile and sends a report to Mattermost"""
    # Parse website
    scraper = WaniKaniScraper(username)
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
