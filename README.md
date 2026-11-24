# 香港每日著數雷達 / HK Jetso Radar

Static GitHub Pages site. `index.html` loads `./deals.json`. A scheduled Action refreshes that file from Hong Kong deal RSS feeds.

## GitHub Actions secrets

Add these under **Settings → Secrets and variables → Actions**. Do not commit keys.

| Secret | Required | Used for |
| --- | --- | --- |
| `GEMINI_API_KEY` | Yes | Gemini filtering. The fetch script stops if this is missing. |
| `TELEGRAM_BOT_TOKEN` | No | Telegram alerts for newly added deals. Skipped when empty. |
| `TELEGRAM_CHAT_ID` | No | Telegram chat that receives those alerts. Skipped when empty. |
| `THREADS_ACCESS_TOKEN` | No | Threads 關鍵字搜尋。未設定就略過，RSS 同 Gemini 照跑。 |

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

## Threads 網上報料

到 Meta 建立一個 Threads app，然後喺 GitHub **Settings → Secrets and variables → Actions** 新增 secret：`THREADS_ACCESS_TOKEN`。

公開關鍵字搜尋要經 Meta App Review 批准 `threads_keyword_search`。未批准之前，API 只會搜尋呢個 token 擁有者自己嘅帖文。沒有 token 時，自動更新會略過 Threads，唔會令成個 job 失敗。

搜尋關鍵字：優惠、平、折扣、抵。用官方 Keyword Search：`GET https://graph.threads.com/v1.0/keyword_search`（`search_type=RECENT`，`search_mode=KEYWORD`）。Gemini 只保留真正嘅香港著數，分類固定為「網上報料」。

## GitHub Pages

Publish the default branch from the repository root (`/` ). The page and `deals.json` stay side by side, so the relative fetch works on Pages.
