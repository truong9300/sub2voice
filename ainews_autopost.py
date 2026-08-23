#!/usr/bin/env python3
"""
ainews_autopost.py — Tự động đăng tin tức AI hàng ngày lên Facebook fanpage.

Chạy trên VPS (Osaka) qua cron, VD mỗi tối 20:00 VN:
  0 13 * * * /usr/bin/python3 /home/opc/ainews_autopost.py >> /home/opc/ainews.log 2>&1

Yêu cầu env:
  FB_PAGE_ID        — ID fanpage
  FB_PAGE_TOKEN     — Page Access Token (pages_manage_posts)
  (tuỳ chọn) NEWS_QUERY — từ khóa tìm, mặc định "AI artificial intelligence"

Lưu ý: New Pages Experience có thể ẩn bài API với non-followers.
Nếu muốn chắc chắn hiển thị, set DRY_RUN=1 để chỉ in nội dung ra log, anh copy-paste thủ công.
"""
import os, sys, json, urllib.parse, urllib.request, subprocess, datetime, re

PAGE_ID = os.environ.get("FB_PAGE_ID", "")
PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
QUERY = os.environ.get("NEWS_QUERY", "AI artificial intelligence breakthrough")
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

def log(m):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {m}", flush=True)

def web_search_news(query, limit=5):
    """Dùng web_search tool thay thế bằng subprocess gọi hermes? Ở đây dùng OSS mồi.
    Nếu chạy trên VPS không có tool Hermes, dùng rigid RSS (Google News)."""
    # Google News RSS (không cần key)
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=vi&gl=VN&ceid=VN:vi"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
        items = re.findall(r"<item>(.*?)</item>", data, re.S)[:limit]
        news = []
        for it in items:
            title = re.search(r"<title>(.*?)</title>", it, re.S)
            link = re.search(r"<link>(.*?)</link>", it, re.S)
            pub = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
            if title:
                news.append({
                    "title": title.group(1).strip(),
                    "link": link.group(1).strip() if link else "",
                    "pub": pub.group(1).strip() if pub else "",
                })
        return news
    except Exception as e:
        log(f"news fetch err: {e}")
        return []

def format_post(news):
    if not news:
        return None
    today = datetime.datetime.now().strftime("%d/%m/%Y")
    lines = [f"🤖 TIN TỨC AI NỔI BẬT — {today}\n"]
    for i, n in enumerate(news, 1):
        lines.append(f"{i}. {n['title']}")
        if n["link"]:
            lines.append(f"   🔗 {n['link']}")
        lines.append("")
    lines.append("#AI #ArtificialIntelligence #TinTucAI #CongNghe")
    return "\n".join(lines)

def post_to_page(message):
    if DRY_RUN:
        log("DRY_RUN — không đăng thật:")
        log(message)
        return "DRY_RUN"
    data = urllib.parse.urlencode({"message": message, "access_token": PAGE_TOKEN}).encode()
    url = f"https://graph.facebook.com/v22.0/{PAGE_ID}/feed"
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=20).read())
        if "id" in resp:
            log(f"ĐÃ ĐĂNG OK: {resp['id']}")
            return resp["id"]
        else:
            log(f"LỖI FB: {resp}")
            return None
    except Exception as e:
        log(f"post err: {e}")
        return None

def main():
    log("=== Bắt đầu chạy ainews_autopost ===")
    if not PAGE_ID or not PAGE_TOKEN:
        log("THIẾU FB_PAGE_ID hoặc FB_PAGE_TOKEN — chỉ chạy DRY_RUN")
        global DRY_RUN; DRY_RUN = True
    news = web_search_news(QUERY)
    log(f"Tìm được {len(news)} tin")
    post = format_post(news)
    if post:
        post_to_page(post)
    else:
        log("Không có tin tức để đăng")
    log("=== Xong ===")

if __name__ == "__main__":
    main()
