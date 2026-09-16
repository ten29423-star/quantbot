"""
News bot: pulls RSS feeds, tags each new article by keyword-based category,
skips already-sent articles, and pushes new ones to a Telegram chat.

Run this on a schedule (see .github/workflows/run.yml). State (which
articles were already sent) is kept in seen_ids.json, which the workflow
commits back to the repo after each run.
"""

import json
import os
import sys
import time
import hashlib

import feedparser
import requests

import datetime

CONFIG_PATH = "config.json"
SEEN_PATH = "seen_ids.json"
STATS_PATH = "stats.json"
MAX_SEEN_ENTRIES = 5000  # cap so the file doesn't grow forever
MAX_STATS_DAYS = 90  # keep last ~3 months of daily counts


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def entry_id(entry, feed_url):
    """Build a stable unique id for an RSS entry."""
    raw = entry.get("id") or entry.get("link") or (feed_url + entry.get("title", ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def categorize(title, summary, categories, default_category):
    text = (title + " " + summary).lower()
    for cat_name, cat_data in categories.items():
        for kw in cat_data["keywords"]:
            if kw.lower() in text:
                return cat_name
    return default_category


def send_telegram_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}", file=sys.stderr)
    return resp.ok


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN env var is not set", file=sys.stderr)
        sys.exit(1)

    config = load_json(CONFIG_PATH, None)
    if config is None:
        print(f"ERROR: {CONFIG_PATH} not found", file=sys.stderr)
        sys.exit(1)

    chat_id = config["telegram_chat_id"]
    categories = config["categories"]
    default_emoji = config.get("default_emoji", "⚪")
    default_category = config.get("default_category", "Other")

    seen_ids = load_json(SEEN_PATH, [])
    seen_set = set(seen_ids)

    new_seen = list(seen_ids)  # will append to this
    sent_count = 0

    for feed_url in config["rss_sources"]:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"Failed to fetch {feed_url}: {e}", file=sys.stderr)
            continue

        if feed.bozo and not feed.entries:
            print(f"Warning: could not parse {feed_url} ({feed.bozo_exception})", file=sys.stderr)
            continue

        for entry in feed.entries:
            eid = entry_id(entry, feed_url)
            if eid in seen_set:
                continue

            title = entry.get("title", "(no title)")
            link = entry.get("link", "")
            summary = entry.get("summary", "")

            category = categorize(title, summary, categories, default_category)
            emoji = categories.get(category, {}).get("emoji", default_emoji)

            message = f"{emoji} <b>{category}</b>\n{title}\n{link}"

            if send_telegram_message(bot_token, chat_id, message):
                sent_count += 1
                seen_set.add(eid)
                new_seen.append(eid)
                time.sleep(0.5)  # be gentle with Telegram's rate limits

    # Cap the seen list so the file doesn't grow forever (keep most recent)
    if len(new_seen) > MAX_SEEN_ENTRIES:
        new_seen = new_seen[-MAX_SEEN_ENTRIES:]

    save_json(SEEN_PATH, new_seen)

    # Update per-day stats
    stats = load_json(STATS_PATH, {})
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    stats[today] = stats.get(today, 0) + sent_count
    # Keep only the most recent MAX_STATS_DAYS days
    if len(stats) > MAX_STATS_DAYS:
        for old_day in sorted(stats.keys())[:-MAX_STATS_DAYS]:
            del stats[old_day]
    save_json(STATS_PATH, stats)

    print(f"Done. Sent {sent_count} new article(s). Today's total: {stats[today]}")


if __name__ == "__main__":
    main()
