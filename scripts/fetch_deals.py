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
RSS_FEEDS = [
    ("JetsoClub", "https://www.jetsoclub.com/feed/"),
    ("FlyAgain", "https://flyagain.la/feed/"),
    ("MeetHK", "https://www.meethk.com/feed/"),
    ("RunHotel", "https://www.runhotel.hk/feed/"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HKJetsoRadar/1.1; +https://github.com)"
}


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
                        "source": source_name,
                        "title": title,
                        "summary": summary,
                        "url": link,
                    }
                )
        except Exception as e:
            print(f"[WARN] Failed to fetch {source_name}: {e}")
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
請閱讀以下最新 RSS 文章列表，抽出有價值嘅香港限時優惠、搶優惠券、現金券、優惠碼、買一送一、平機票、自助餐或電子錢包著數（過濾無關新聞或純廣告）。

規則：
1. 若文章有明確開搶時間（例如中午12點、下午3點、晚上9點），`time` 填 24 小時制 "HH:MM"（如 "12:00"、"21:00"）；否則填 "全日"。
2. `category` 必須係以下其中一個："優惠券搶購"、"機票旅遊"、"飲食著數"、"酒店自助餐"、"網購信用卡"、"其他"。
   - 凡涉及搶現金券、電子優惠券、PayMe/AlipayHK/八達通搶券、Klook/KKday/Trip.com/外賣/超市優惠碼，優先歸類為 "優惠券搶購"。
3. `where_to_grab` 寫清楚去邊度搶（15字內，例如："PayMe App 搶券頁"、"AlipayHK 首頁"、"Klook App 活動頁"、"7-Eleven 門市"）。
4. `promo_code` 如果文章有明確優惠碼（如 "HK100"）就填入該代碼；冇就填 ""。
5. 如果係突發快閃、限量搶券、買一送一或極抵價，`is_flash` 設為 true。
6. `title` 用簡潔港式中文（25字內）；`summary` 用一句講重點（45字內，包含面額／折扣／門檻）。
7. 嚴格回傳 JSON Array，如果全部都唔值得收錄就回傳 []。

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

    if not new_rss_items:
        print("No new RSS items found. Skipping Gemini API call.")
        return

    print(f"Found {len(new_rss_items)} new RSS items. Calling Gemini...")
    extracted = extract_deals_with_gemini(new_rss_items, now.strftime("%Y-%m-%d %H:%M"))

    for item in new_rss_items:
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

    newly_added = []
    for d in extracted:
        url = d.get("url", "").strip()
        if not url:
            continue
        deal_id = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
        if deal_id in existing_ids:
            continue
        deal_obj = {
            "id": deal_id,
            "time": d.get("time", "全日"),
            "title": d.get("title", "香港著數"),
            "platform": d.get("platform", "著數情報"),
            "where_to_grab": d.get("where_to_grab", ""),
            "promo_code": d.get("promo_code", ""),
            "category": d.get("category", "其他"),
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
