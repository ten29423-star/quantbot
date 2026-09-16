# News Bot

Pulls RSS feeds every 5 minutes, tags each new article by category
(keyword-based, no AI), skips already-sent articles, and sends new ones
to your Telegram chat.

## Setup (one-time)

1. **Create a new GitHub repository**, make it **Public** (so Actions runs
   free and unlimited). Name it whatever you like, e.g. `news-bot`.

2. **Upload these files** to the repo, keeping the folder structure:
   ```
   news-bot/
   ├── .github/
   │   └── workflows/
   │       └── run.yml
   ├── config.json
   ├── main.py
   ├── requirements.txt
   └── README.md
   ```
   Easiest way: on the repo page, click "Add file" → "Upload files", drag
   all of them in (GitHub preserves the `.github/workflows/run.yml` path
   if you drag the whole folder, or create the folders manually first).

3. **Add your bot token as a secret** (never put it directly in the code):
   - Go to your repo → **Settings** → **Secrets and variables** → **Actions**
   - Click **New repository secret**
   - Name: `TELEGRAM_BOT_TOKEN`
   - Value: your bot token from BotFather
   - Save

4. **Check `config.json`** — `telegram_chat_id` is already set to your
   chat id. Edit `rss_sources` or `categories` any time, no code changes
   needed.

5. **Enable Actions** if prompted (Actions tab → "I understand my
   workflows, go ahead and enable them").

6. **Run it once manually** to test: Actions tab → "Run news bot" →
   "Run workflow" button. Check the logs, and check your Telegram chat
   for messages.

Once it works, it runs automatically every 5 minutes — nothing more to do.

## Editing categories/keywords later

Open `config.json` in the repo (GitHub lets you edit files directly in
the browser — pencil icon), add a new category block or new keywords to
an existing one, commit. Next run picks it up automatically.

## Adding more RSS feeds

Same file, add a URL string to the `rss_sources` list.

## Notes

- `seen_ids.json` is created automatically after the first run and keeps
  track of what's already been sent (capped at the last 5000 entries).
- If a message fails to send (rare, e.g. Telegram rate limit), it will
  just get retried in the next run.
