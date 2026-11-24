import hashlib
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import feedparser
import requests

HKT = ZoneInfo("Asia/Hong_Kong")
DEALS_FILE = "deals.json"

# 香港主要著數／搶券／機票／酒店 RSS 來源
# JetsoClub 係 Blogger，官方 Atom feed 係 /feeds/posts/default（/feed/ 唔係呢個 feed）。
# JetsoToday 係網站 <link rel="alternate"> 公布嘅 WordPress RSS。
RSS_FEEDS = [
    ("JetsoClub", "https://www.jetsoclub.com/feeds/posts/default"),
    ("JetsoToday", "https://www.jetsotoday.com/feed/"),
    ("FlyAgain", "https://flyagain.la/feed/"),
    ("MeetHK", "https://www.meethk.com/feed/"),
    ("RunHotel", "https://www.runhotel.hk/feed/"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HKJetsoRadar/1.1; +https://github.com)"
}

# 官方 Threads Keyword Search。文件示例係 graph.threads.com（graph.threads.net 同樣可用）。
# https://developers.facebook.com/docs/threads/keyword-search
THREADS_KEYWORDS = ["優惠", "平", "折扣", "抵"]
THREADS_SEARCH_URL = "https://graph.threads.com/v1.0/keyword_search"
THREADS_FIELDS = "id,text,permalink,timestamp,username"
THREADS_LIMIT = 10
# 官方 Custom Search JSON API。dateRestrict=d1 係過去一日。
# https://developers.google.com/custom-search/v1/using_rest
GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
GOOGLE_QUERY = "香港 (當日優惠 OR 今日優惠)"
RSS_CATEGORIES = {"優惠券搶購", "機票旅遊", "飲食著數", "酒店自助餐", "網購信用卡", "其他"}


def load_data() -> dict:
    if os.path.exists(DEALS_FILE):
        with open(DEALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"updated_at": "", "seen_urls": [], "deals": []}


def fetch_new_rss_items(seen_urls: set) -> list:
    new_items = []
    for source_name, feed_url in RSS_FEEDS:
        try:
            resp = requests.get(feed_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:10]:
                link = entry.get("link", "").strip()
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "").strip()[:350]
                if not link or not title or link in seen_urls:
                    continue
                new_items.append(
                    {
                        "origin": "rss",
                        "source": source_name,
                        "title": title,
                        "summary": summary,
                        "url": link,
                    }
                )
        except Exception as e:
            print(f"[WARN] Failed to fetch {source_name}: {e}")
    return new_items


def fetch_new_threads_items(seen_urls: set) -> list:
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        print("[WARN] THREADS_ACCESS_TOKEN is missing. Skipping Threads keyword search.")
        return []

    new_items = []
    seen_now = set(seen_urls)
    for keyword in THREADS_KEYWORDS:
        try:
            resp = requests.get(
                THREADS_SEARCH_URL,
                params={
                    "q": keyword,
                    "search_type": "RECENT",
                    "search_mode": "KEYWORD",
                    "fields": THREADS_FIELDS,
                    "limit": THREADS_LIMIT,
                    "access_token": token,
                },
                timeout=20,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "error"
            print(f"[WARN] Threads keyword search failed for {keyword}: HTTP {status}")
            continue
        except Exception as e:
            print(f"[WARN] Threads keyword search failed for {keyword}: {type(e).__name__}")
            continue

        if isinstance(payload, dict) and payload.get("error"):
            err = payload["error"] if isinstance(payload["error"], dict) else {}
            print(f"[WARN] Threads keyword search failed for {keyword}: API {err.get('code', 'error')}")
            continue

        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            print(f"[WARN] Threads keyword search for {keyword} returned no data list.")
            continue

        for post in rows:
            if not isinstance(post, dict):
                continue
            permalink = (post.get("permalink") or "").strip().rstrip("/")
            text = (post.get("text") or "").strip()
            if not permalink or not text or permalink in seen_now:
                continue
            seen_now.add(permalink)
            username = (post.get("username") or "").strip().lstrip("@")
            new_items.append(
                {
                    "origin": "threads",
                    "source": "Threads",
                    "username": username,
                    "title": text.replace("\n", " ")[:80],
                    "summary": text[:350],
                    "url": permalink,
                    "timestamp": post.get("timestamp") or "",
                }
            )
    print(f"Threads keyword search: {len(new_items)} new posts.")
    return new_items


def fetch_new_google_items(seen_urls: set) -> list:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    cse_id = os.environ.get("GOOGLE_CSE_ID", "").strip()
    if not api_key or not cse_id:
        print("[WARN] GOOGLE_API_KEY or GOOGLE_CSE_ID is missing. Skipping Google deal search.")
        return []

    try:
        resp = requests.get(
            GOOGLE_SEARCH_URL,
            params={
                "key": api_key,
                "cx": cse_id,
                "q": GOOGLE_QUERY,
                "dateRestrict": "d1",
                "cr": "countryHK",
                "gl": "hk",
                "hl": "zh-HK",
                "num": 10,
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "error"
        print(f"[WARN] Google deal search failed: HTTP {status}")
        return []
    except Exception as e:
        print(f"[WARN] Google deal search failed: {type(e).__name__}")
        return []

    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"] if isinstance(payload["error"], dict) else {}
        print(f"[WARN] Google deal search failed: API {err.get('code', 'error')}")
        return []

    rows = payload.get("items") if isinstance(payload, dict) else None
    if not rows:
        print("Google deal search: 0 new results.")
        return []

    new_items = []
    seen_now = set(seen_urls)
    for row in rows:
        if not isinstance(row, dict):
            continue
        link = (row.get("link") or "").strip()
        title = (row.get("title") or "").strip()
        snippet = (row.get("snippet") or "").strip()
        if not link or not title or link in seen_now:
            continue
        seen_now.add(link)
        host = (row.get("displayLink") or "").strip()
        new_items.append(
            {
                "origin": "google",
                "source": host or "Google",
                "title": title[:120],
                "summary": snippet[:350],
                "url": link,
            }
        )
    print(f"Google deal search: {len(new_items)} new results.")
    return new_items


def extract_deals_with_gemini(items: list, now_str: str) -> list:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY secret.")

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-3.5-flash-lite:generateContent?key={api_key}"
    )

    prompt = f"""你係香港著數及搶券情報編輯。現在香港時間係 {now_str}。
請閱讀以下最新情報（RSS 文章、Google 當日搜尋結果或 Threads 帖文），抽出有價值嘅香港限時優惠、搶優惠券、現金券、優惠碼、買一送一、平機票、自助餐或電子錢包著數。過濾無關新聞、純廣告，以及同香港著數無關嘅帖文。

規則：
1. 若內容有明確開搶時間（例如中午12點、下午3點、晚上9點），`time` 填 24 小時制 "HH:MM"（如 "12:00"、"21:00"）；否則填 "全日"。
2. `origin` 唔係 "threads" 嘅項目（RSS 或 Google）`category` 必須係以下其中一個："優惠券搶購"、"機票旅遊"、"飲食著數"、"酒店自助餐"、"網購信用卡"、"其他"。唔好用 "網上報料"。
   - `origin` 係 "google" 嘅結果只保留當日或仍然有效嘅香港優惠；過期、非香港或唔係著數嘅結果要丟棄。
   - 凡涉及搶現金券、電子優惠券、PayMe/AlipayHK/八達通搶券、Klook/KKday/Trip.com/外賣/超市優惠碼，優先歸類為 "優惠券搶購"。
3. `origin` 係 "threads" 嘅帖文：只保留真正嘅香港著數、折扣、優惠券、平機票或飲食優惠。關鍵字「平」好闊，心情分享、新聞、抱怨、非香港、冇實際優惠嘅帖要丟棄。保留嘅 `category` 必須係 "網上報料"。`platform` 用 "@" 加 username；冇 username 就填 "Threads"。`url` 必須原樣使用該帖 permalink。
4. `where_to_grab` 寫清楚去邊度搶（15字內，例如："PayMe App 搶券頁"、"AlipayHK 首頁"、"Klook App 活動頁"、"7-Eleven 門市"）。Threads 帖可以填 "Threads 帖文"。
5. `promo_code` 如果內容有明確優惠碼（如 "HK100"）就填入該代碼；冇就填 ""。
6. 如果係突發快閃、限量搶券、買一送一或極抵價，`is_flash` 設為 true。
7. `title` 用簡潔港式中文（25字內）；`summary` 用一句講重點（45字內，包含面額／折扣／門檻）。
8. 嚴格回傳 JSON Array，如果全部都唔值得收錄就回傳 []。

輸出格式：
[
  {{
    "time": "12:00",
    "title": "標題",
    "platform": "平台或商戶名",
    "where_to_grab": "去邊度搶",
    "promo_code": "",
    "category": "優惠券搶購",
    "summary": "重點摘要",
    "url": "原文連結",
    "is_flash": true
  }}
]

文章列表：
{json.dumps(items, ensure_ascii=False)}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    resp = requests.post(endpoint, json=payload, timeout=45)
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)
    return parsed if isinstance(parsed, list) else []


def send_telegram_alert(new_deals: list):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id or not new_deals:
        return

    lines = ["🔥 <b>香港最新著數／搶券更新</b>\n"]
    for d in new_deals[:8]:
        badge = "🎟️" if d.get("category") == "優惠券搶購" else ("⚡" if d.get("is_flash") else "🏷️")
        code_line = f"🔑 優惠碼：<code>{d['promo_code']}</code>\n" if d.get("promo_code") else ""
        where_line = f"📍 地點：{d['where_to_grab']}\n" if d.get("where_to_grab") else ""
        lines.append(
            f"{badge} <b>[{d['time']}] {d['title']}</b>\n"
            f"{where_line}"
            f"{code_line}"
            f"📌 {d['platform']}｜{d['summary']}\n"
            f"👉 <a href=\"{d['url']}\">即刻去搶</a>\n"
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
    except Exception as e:
        print(f"[WARN] Telegram notify failed: {e}")


def sort_key(deal: dict):
    t = deal.get("time", "全日")
    if len(t) == 5 and ":" in t:
        return (0, t)
    return (1, "99:99")


def main():
    now = datetime.now(HKT)
    now_iso = now.isoformat(timespec="seconds")
    data = load_data()

    seen_urls = set(data.get("seen_urls", []))
    new_rss_items = fetch_new_rss_items(seen_urls)
    new_threads_items = fetch_new_threads_items(seen_urls)
    new_google_items = fetch_new_google_items(seen_urls)
    new_items = new_rss_items + new_threads_items + new_google_items

    if not new_items:
        print("No new RSS, Threads, or Google items found. Skipping Gemini API call.")
        return

    print(
        f"Found {len(new_rss_items)} new RSS items, "
        f"{len(new_threads_items)} new Threads posts, and "
        f"{len(new_google_items)} new Google results. Calling Gemini..."
    )
    extracted = extract_deals_with_gemini(new_items, now.strftime("%Y-%m-%d %H:%M"))

    for item in new_items:
        seen_urls.add(item["url"])
    seen_list = list(seen_urls)[-300:]

    cutoff = now - timedelta(hours=36)
    existing_deals = []
    existing_ids = set()
    for d in data.get("deals", []):
        try:
            added = datetime.fromisoformat(d.get("added_at", now_iso))
            if added >= cutoff:
                existing_deals.append(d)
                existing_ids.add(d["id"])
        except Exception:
            continue

    threads_by_url = {item["url"]: item for item in new_threads_items}
    google_by_url = {item["url"]: item for item in new_google_items}
    newly_added = []
    for d in extracted:
        url = (d.get("url") or "").strip()
        if not url:
            continue
        thread = threads_by_url.get(url) or threads_by_url.get(url.rstrip("/"))
        if thread is not None:
            url = thread["url"]
        deal_id = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        if deal_id in existing_ids:
            continue
        if thread is not None:
            username = (thread.get("username") or "").strip().lstrip("@")
            category = "網上報料"
            platform = f"@{username}" if username else "Threads"
        else:
            category = d.get("category", "其他")
            if category not in RSS_CATEGORIES:
                category = "其他"
            platform = d.get("platform") or ""
            google_item = google_by_url.get(url)
            if google_item is not None and not platform:
                platform = google_item.get("source") or "Google"
            if not platform:
                platform = "著數情報"
        deal_obj = {
            "id": deal_id,
            "time": d.get("time", "全日"),
            "title": d.get("title", "香港著數"),
            "platform": platform,
            "where_to_grab": d.get("where_to_grab", ""),
            "promo_code": d.get("promo_code", ""),
            "category": category,
            "summary": d.get("summary", ""),
            "url": url,
            "is_flash": bool(d.get("is_flash", False)),
            "added_at": now_iso,
        }
        existing_deals.append(deal_obj)
        existing_ids.add(deal_id)
        newly_added.append(deal_obj)

    existing_deals.sort(key=sort_key)

    output = {
        "updated_at": now_iso,
        "seen_urls": seen_list,
        "deals": existing_deals,
    }

    with open(DEALS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Updated {DEALS_FILE}: +{len(newly_added)} new deals (total {len(existing_deals)}).")
    if newly_added:
        send_telegram_alert(newly_added)


if __name__ == "__main__":
    main()
