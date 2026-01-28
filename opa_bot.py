import requests
import feedparser
import hashlib
import json
import os
from datetime import datetime

# Cargar desde variables de entorno (configúralas en GitHub Secrets o en tu entorno local)
BOT_TOKEN = os.environ.get('8513075677:AAEd5qkb1nx9wYnPf5ecaO31pJXFBiuNXRs')
CHAT_ID = os.environ.get('1125679152')
DB_FILE = "seen.json"

# Palabras clave expandidas para OPA/ofertas de adquisición (insensible a mayúsculas)
KEYWORDS = [
    "opa",
    "oferta pública de adquisición",
    "oferta publica de adquisicion",
    "tender offer",
    "takeover",
    "cash offer",
    "voluntary offer",
    "oferta de exclusión",
    "squeeze-out"
]

# Feeds RSS relevantes (enfocados en España/Europa financiera y noticias)
RSS_FEEDS = [
    "https://www.cnmv.es/portal/RSS/RssHandler.ashx?fac=HECHOSRELEV",  # CNMV España (clave para OPAs oficiales)
    "https://www.bolsamadrid.es/rss/RSS.ashx?feed=Todo",  # Bolsa de Madrid
    "https://www.expansion.com/rss/mercados.xml",  # Expansion (España)
    "https://www.amf-france.org/en/rss",  # AMF Francia (mantenido del original)
    "https://www.consob.it/web/consob-and-its-activities/rss",  # CONSOB Italia (para cobertura EU más amplia)
    "https://www.cincodias.com/rss/mercados",  # Cinco Días (noticias financieras España)
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
    if not BOT_TOKEN or not CHAT_ID:
        print("Error: BOT_TOKEN o CHAT_ID no configurados.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error al enviar mensaje de Telegram: {e}")

def is_opa(text):
    text = text.lower()
    return any(k.lower() in text for k in KEYWORDS)

def check_rss():
    seen = load_seen()
    new_alerts = 0
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo:
                print(f"Advertencia: Problema al parsear feed {feed_url}: {feed.bozo_exception}")
                continue
            for entry in feed.entries:
                text = (entry.title + " " + entry.get("summary", "") + " " + entry.get("description", "")).lower()
                # ID único: hash de enlace + título para manejar enlaces similares
                uid = hashlib.md5((entry.link + entry.title).encode()).hexdigest()
                if uid in seen:
                    continue
                if is_opa(text):
                    pub_time = entry.get("published", datetime.now().strftime('%Y-%m-%d %H:%M'))
                    msg = (
                        "🚨 *¡OPA Detectada!*\n\n"
                        f"**Título:** {entry.title}\n"
                        f"**Fuente:** {feed.feed.title if 'title' in feed.feed else feed_url}\n"
                        f"**Hora de publicación:** {pub_time}\n"
                        f"**Alerta generada:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                        f"[Leer más]({entry.link})"
                    )
                    send_telegram(msg)
                    seen.add(uid)
                    new_alerts += 1
        except Exception as e:
            print(f"Error procesando feed {feed_url}: {e}")
    save_seen(seen)
    print(f"Feeds comprobados. Nuevas alertas: {new_alerts}")

if __name__ == "__main__":
    check_rss()
