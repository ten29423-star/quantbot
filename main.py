"""
News bot: pulls RSS feeds, tags each new article by keyword-based category
(an article can get multiple category tags), applies a sport exclusion
filter (unless an Animal match overrides it), skips already-sent article
links, and pushes new ones to a Telegram chat. Also tracks per-source
health and alerts if a feed has been failing.

Run this on a schedule (see .github/workflows/run.yml). State is kept in
seen_ids.json, stats.json and source_health.json, which the workflow
commits back to the repo after each run.
"""

import json
import os
import sys
import time
import hashlib
import re
import datetime
from urllib.parse import urlparse

import feedparser
import requests

CONFIG_PATH = "config.json"
SEEN_PATH = "seen_ids.json"
STATS_PATH = "stats.json"
HEALTH_PATH = "source_health.json"
MAX_SEEN_ENTRIES = 5000
MAX_STATS_DAYS = 90


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def entry_id(entry, feed_url):
    """Build a stable unique id for an RSS entry (same link = same id)."""
    raw = entry.get("id") or entry.get("link") or (feed_url + entry.get("title", ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def source_name(feed, feed_url):
    """Human-readable source name for the message, e.g. 'TechCrunch'."""
    title = feed.feed.get("title") if hasattr(feed, "feed") else None
    if title:
        return title
    domain = urlparse(feed_url).netloc.replace("www.", "")
    return domain


def contains_word(text, phrase):
    """True if `phrase` appears in `text` as whole word(s), not as a substring of a longer word."""
    pattern = r"\b" + re.escape(phrase.lower()) + r"\b"
    return re.search(pattern, text) is not None


def matches_category(text, cat_data):
    """A category matches if any keyword is found AND no exclude_keyword is found."""
    for excl in cat_data.get("exclude_keywords", []):
        if contains_word(text, excl):
            return False
    for kw in cat_data["keywords"]:
        if contains_word(text, kw):
            return True
    return False


def categorize(title, summary, config):
    """
    Returns a list of matched category names, or None if the article
    should be skipped entirely (sport-excluded with no Animal override).
    Empty list means no specific category matched -> caller uses "Other".
    """
    text = (title + " " + summary).lower()
    categories = config["categories"]

    matched = [name for name, data in categories.items() if matches_category(text, data)]

    is_sport = any(contains_word(text, kw) for kw in config.get("sport_exclude_keywords", []))
    if is_sport and "Animal" not in matched:
        return None  # skip: pure sports noise

    return matched


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


def update_source_health(health, feed_url, ok, today, alert_after_days, bot_token, chat_id):
    """Track consecutive-failure days per source; alert once per day if threshold passed."""
    entry = health.get(feed_url, {"last_success": today, "last_alert": None})

    if ok:
        entry["last_success"] = today
    else:
        last_success = datetime.datetime.strptime(entry["last_success"], "%Y-%m-%d").date()
        days_down = (datetime.datetime.strptime(today, "%Y-%m-%d").date() - last_success).days
        if days_down >= alert_after_days and entry.get("last_alert") != today:
            name = urlparse(feed_url).netloc
            send_telegram_message(
                bot_token, chat_id,
                f"⚠️ Source not responding for {days_down} day(s): {name}\n{feed_url}"
            )
            entry["last_alert"] = today

    health[feed_url] = entry


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
    default_emoji = config.get("default_emoji", "⚪")
    default_category = config.get("default_category", "Other")
    alert_after_days = config.get("source_health", {}).get("alert_after_days", 1)

    seen_ids = load_json(SEEN_PATH, [])
    seen_set = set(seen_ids)
    new_seen = list(seen_ids)

    stats = load_json(STATS_PATH, {})
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    day_stats = stats.get(today, {"total": 0})

    health = load_json(HEALTH_PATH, {})

    sent_count = 0

    for feed_url in config["rss_sources"]:
        try:
            feed = feedparser.parse(feed_url)
            ok = bool(feed.entries) or not feed.bozo
        except Exception as e:
            print(f"Failed to fetch {feed_url}: {e}", file=sys.stderr)
            feed = None
            ok = False

        update_source_health(health, feed_url, ok, today, alert_after_days, bot_token, chat_id)

        if not feed or not feed.entries:
            if feed and feed.bozo:
                print(f"Warning: could not parse {feed_url} ({feed.bozo_exception})", file=sys.stderr)
            continue

        src_name = source_name(feed, feed_url)

        for entry in feed.entries:
            eid = entry_id(entry, feed_url)
            if eid in seen_set:
                continue

            title = entry.get("title", "(no title)")
            link = entry.get("link", "")
            summary = entry.get("summary", "")

            matched = categorize(title, summary, config)
            if matched is None:
                seen_set.add(eid)  # don't re-check sport-excluded articles every run
                new_seen.append(eid)
                continue

            cat_names = matched if matched else [default_category]
            cat_data_map = config["categories"]
            tags = " ".join(
                f"{cat_data_map.get(c, {}).get('emoji', default_emoji)} <b>{c}</b>"
                for c in cat_names
            )

            message = f"{tags}\n{title}\n<i>{src_name}</i>\n{link}"

            if send_telegram_message(bot_token, chat_id, message):
                sent_count += 1
                seen_set.add(eid)
                new_seen.append(eid)
                day_stats["total"] = day_stats.get("total", 0) + 1
                for c in cat_names:
                    day_stats[c] = day_stats.get(c, 0) + 1
                time.sleep(0.5)

    if len(new_seen) > MAX_SEEN_ENTRIES:
        new_seen = new_seen[-MAX_SEEN_ENTRIES:]
    save_json(SEEN_PATH, new_seen)

    stats[today] = day_stats
    if len(stats) > MAX_STATS_DAYS:
        for old_day in sorted(stats.keys())[:-MAX_STATS_DAYS]:
            del stats[old_day]
    save_json(STATS_PATH, stats)

    save_json(HEALTH_PATH, health)

    print(f"Done. Sent {sent_count} new article(s). Today's total: {day_stats['total']}")


if __name__ == "__main__":
    main()
