# 香港每日著數雷達 / HK Jetso Radar

Static GitHub Pages site. `index.html` loads `./deals.json`. A scheduled Action refreshes that file from Hong Kong deal RSS feeds.

## GitHub Actions secrets

Add these under **Settings → Secrets and variables → Actions**. Do not commit keys.

| Secret | Required | Used for |
| --- | --- | --- |
| `GEMINI_API_KEY` | Yes | Gemini filtering. The fetch script stops if this is missing. |
| `TELEGRAM_BOT_TOKEN` | No | Telegram alerts for newly added deals. Skipped when empty. |
| `TELEGRAM_CHAT_ID` | No | Telegram chat that receives those alerts. Skipped when empty. |

After the secrets are set, open **Actions → Auto Update HK Jetso Deals → Run workflow** once. The seed row in `deals.json` points at that exact workflow name.

## Schedule

Cron (UTC): `0,15,30,45 0-14 * * *`

That is every 15 minutes from 00:00 through 14:45 UTC, which is 08:00 through 22:45 Hong Kong time (UTC+8), including 14:45 UTC = 22:45 HKT. `workflow_dispatch` is also enabled.

## RSS sources

Listed in `scripts/fetch_deals.py`:

- JetsoClub — `https://www.jetsoclub.com/feed/`
- FlyAgain — `https://flyagain.la/feed/`
- MeetHK — `https://www.meethk.com/feed/`
- RunHotel — `https://www.runhotel.hk/feed/`

One failed feed is logged and skipped. Deals already present in `deals.json` are not sent to Telegram again.

## GitHub Pages

Publish the default branch from the repository root (`/` ). The page and `deals.json` stay side by side, so the relative fetch works on Pages.
