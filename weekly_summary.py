"""
Sends a weekly digest to Telegram: total articles sent and per-category
breakdown for the last 7 days, based on stats.json.
Run separately on its own schedule (see .github/workflows/weekly_summary.yml).
"""

import json
import os
import sys
import datetime

import requests

CONFIG_PATH = "config.json"
STATS_PATH = "stats.json"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def send_telegram_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
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
    stats = load_json(STATS_PATH, {})

    today = datetime.date.today()
    last_7_days = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    totals = {}
    grand_total = 0
    for day in last_7_days:
        day_stats = stats.get(day, {})
        for key, count in day_stats.items():
            if key == "total":
                grand_total += count
            else:
                totals[key] = totals.get(key, 0) + count

    if grand_total == 0:
        message = "📊 <b>Weekly digest</b>\nNo articles sent in the last 7 days."
    else:
        lines = [f"📊 <b>Weekly digest</b>", f"Total: {grand_total} articles\n"]
        for cat, count in sorted(totals.items(), key=lambda x: -x[1]):
            lines.append(f"{cat}: {count}")
        message = "\n".join(lines)

    send_telegram_message(bot_token, chat_id, message)
    print("Weekly summary sent.")


if __name__ == "__main__":
    main()
