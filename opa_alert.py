import requests
import feedparser
import hashlib
import json
import os
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import re

# Configuración
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
DB_FILE = "seen.json"

# Keywords FUERTES (solo las que indican claramente OPA/takeover)
STRONG_KEYWORDS = [
    "opa", "oferta pública de adquisición", "oferta publica de adquisicion",
    "tender offer", "takeover bid", "public takeover", "mandatory offer", "squeeze-out",
    "offre publique d'achat", "offre publique obligatoire", "opa obligatoire",
    "offerta pubblica di acquisto", "opa obbligatoria",
    "übernahmeangebot", "pflichtangebot", "öffentliches übernahmeangebot",
    "openbaar bod", "openbaar overnamebod", "verplicht bod",
    "offentligt uppköpserbjudande", "obligatoriskt bud",
    "oferta pública de aquisição", "opa obrigatória",
    "publiczna oferta przejęcia", "obowiązkowa oferta",
]

# Frases a excluir (falsos positivos comunes)
EXCLUDE_PATTERNS = [
    "remain vulnerable", "treacherous calm", "trendzicht", "trend monitor", "trend monitor 2026",
    "financial markets remain", "mercados financieros permanecen", "permanecen inalterados",
    "markets remain", "vulnerable", "geopolitical tensions", "hyper-personalisation"
]

RSS_FEEDS = [
    "https://www.cnmv.es/portal/RSS/RssHandler.ashx?fac=HECHOSRELEV",
    "https://www.bolsamadrid.es/rss/RSS.ashx?feed=Todo",
    "https://www.expansion.com/rss/mercados.xml",
    "https://www.cincodias.com/rss/mercados",
    "https://www.amf-france.org/en/rss",
    "https://www.consob.it/web/consob-and-its-activities/rss",
    "https://www.fca.org.uk/rss/news",
    "https://www.bafin.de/EN/Service/RSS/rss_artikel_en.html",
    "https://www.afm.nl/en/rss",  # Si sigue dando problemas, comenta esta línea
    "https://www.fi.se/en/rss/",
    "https://www.cmvm.pt/en/rss",
    "https://www.knf.gov.pl/en/rss",
    "https://www.ecb.europa.eu/home/html/rss.en.html",
    "https://www.esma.europa.eu/rss",
    "https://www.euronext.com/en/rss",
]

def normalize_url(url):
    if not url:
        return url
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, '', parsed.fragment))

def load_seen():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_seen(seen):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        print("Error: BOT_TOKEN o CHAT_ID no configurados.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"Enviado: {msg[:100]}...")
    except Exception as e:
        print(f"Error Telegram: {e}")

def is_opa(text):
    text_lower = text.lower()
    
    # Excluir falsos positivos
    if any(pattern in text_lower for pattern in EXCLUDE_PATTERNS):
        print(f"Excluido por patrón: {text_lower[:100]}...")
        return False
    
    # Requiere al menos una keyword fuerte
    has_match = any(keyword.lower() in text_lower for keyword in STRONG_KEYWORDS)
    
    if has_match:
        print(f"OPA detectada: {text_lower[:100]}...")
    else:
        print(f"No OPA: {text_lower[:100]}...")
    
    return has_match

def check_rss():
    seen = load_seen()
    new_alerts = 0
    
    for feed_url in RSS_FEEDS:
        print(f"Procesando: {feed_url}")
        try:
            feed = feedparser.parse(feed_url, agent="OPA-Bot/1.0 +https://github.com/elpa82-dev/opa-alerts-bot")
            if feed.bozo:
                print(f"  Problema feed: {feed.bozo_exception}")
                continue
            
            for entry in feed.entries:
                link = entry.get('link', '')
                if not link:
                    continue
                
                clean_link = normalize_url(link)
                clean_title = re.sub(r'\s+', ' ', entry.title.strip()) if entry.title else ''
                uid_input = clean_link + clean_title
                uid = hashlib.md5(uid_input.encode('utf-8')).hexdigest()
                
                if uid in seen:
                    print(f"  Ya visto: {uid} - {clean_title[:60]}")
                    continue
                
                text = (
                    entry.get('title', '') + " " +
                    entry.get('summary', '') + " " +
                    entry.get('description', '')
                )
                
                if is_opa(text):
                    pub_time = entry.get('published', datetime.now().strftime('%Y-%m-%d %H:%M'))
                    source = feed.feed.get('title', feed_url.split('//')[-1].split('/')[0])
                    
                    msg = (
                        "🚨 *¡OPA Detectada!*\n\n"
                        f"**Título:** {entry.title}\n"
                        f"**Fuente:** {source}\n"
                        f"**Publicado:** {pub_time}\n"
                        f"**Alerta:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                        f"[Leer]({link})"
                    )
                    send_telegram(msg)
                    seen.add(uid)
                    new_alerts += 1
                # else: print(f"  No OPA: {clean_title[:60]}")
        except Exception as e:
            print(f"Error en {feed_url}: {e}")
    
    save_seen(seen)
    print(f"Finalizado. Alertas nuevas: {new_alerts}")

if __name__ == "__main__":
    check_rss()
