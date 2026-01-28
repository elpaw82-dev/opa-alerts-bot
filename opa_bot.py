import requests
import feedparser
import hashlib
import json
import os
from datetime import datetime

BOT_TOKEN = os.environ[8513075677:AAEd5qkb1nx9wYnPf5ecaO31pJXFBiuNXRs]
CHAT_ID = os.environ[1125679152]

DB_FILE = "seen.json"

KEYWORDS = [
    "opa",
    "oferta pública de adquisición",
    "tender offer",
    "takeover",
    "cash offer",
    "voluntary offer"
]

RSS_FEEDS = [
    "https://www.amf-france.org/en/rss",
    "https://www.expansion.com/rss/mercados.xml"
]

def load_seen():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(DB_FILE, "w") as f:
        json.dump(list(seen), f)

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def is_opa(text):
    text = text.lower()
    return any(k in text for k in KEYWORDS)

def check_rss():
    seen = load_seen()
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            text = (entry.title + " " + entry.get("summary", "")).lower()
            uid = hashlib.md5(entry.link.encode()).hexdigest()

            if uid in seen:
                continue

            if is_opa(text):
                msg = (
                    "🚨 *OPA detectada*\n\n"
                    f"*Título:* {entry.title}\n"
                    f"*Hora:* {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"{entry.link}"
                )
                send_telegram(msg)
                seen.add(uid)

    save_seen(seen)

if __name__ == "__main__":
    check_rss()
