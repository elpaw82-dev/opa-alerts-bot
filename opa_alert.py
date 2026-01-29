import requests
import feedparser
import hashlib
import json
import os
from datetime import datetime
from urllib.parse import urlparse, urlunparse
import re
from bs4 import BeautifulSoup

# Configuración
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
DB_FILE = "seen.json"

# Keywords FUERTES (detectan inmediatamente)
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
    "opa obligatoria", "obligatoria sobre",  # Específicas CNMV
]

# Keywords secundarias (títulos genéricos)
SECONDARY_KEYWORDS = [
    "ofertas públicas de adquisición", "oferta pública", "adquisición de acciones",
    "ofertas públicas", "opa sobre", "adquisición obligatoria", "compra de acciones"
]

# Frases a excluir (falsos positivos)
EXCLUDE_PATTERNS = [
    "remain vulnerable", "treacherous calm", "trendzicht", "trend monitor", "trend monitor 2026",
    "financial markets remain", "mercados financieros permanecen", "permanecen inalterados",
    "markets remain", "vulnerable", "geopolitical tensions", "hyper-personalisation"
]

# Añade exclusiones más fuertes para recompras y boletines
EXCLUDE_PATTERNS.extend([
    "recompra de acciones", "autocartera", "programas de recompra", "boletin diario",
    "boletín diario", "mtf equity", "estructuras"  # opcional, para los que viste
]
                        
# Lista ampliada de RSS feeds (España + Europa + globales con foco mercados)
RSS_FEEDS = [
    # España - CNMV (el más importante para OPAs oficiales)
    "https://www.cnmv.es/portal/Otra-Informacion-Relevante/RSS.asmx/GetNoticiasCNMV",  # Otra Información Relevante (OIR) - clave para autorizaciones OPA
    "https://www.cnmv.es/portal/RSS/RssHandler.ashx?fac=HECHOSRELEV",               # Hechos Relevantes (prueba, aunque a veces falla)

    # España - Medios y bolsas
    "https://www.expansion.com/rss/mercados.xml",                                  # Expansión Mercados
    "https://www.cincodias.com/rss/mercados",                                      # Cinco Días Mercados
    "http://www.eleconomista.es/rss/rss-mercados.php",                             # El Economista Mercados (del RSS oficial)
    "https://www.bolsasymercados.es/bme-exchange/es/RSS/Regulacion",               # BME Regulación (puede capturar OPAs/reglas)
    "https://www.bolsasymercados.es/MTF_Equity/esp/RSS/Boletin.ashx",              # BME Boletín diario general (noticias bursátiles)

    # Francia
    "https://services.lesechos.fr/rss/les-echos-finance-marches.xml",              # Les Echos Finance & Marchés

    # Italia
    "https://www.ilsole24ore.com/rss/finanza.xml",                                 # Il Sole 24 Ore Finanza
    "https://www.ilsole24ore.com/rss/finanza--quotate-italia.xml",                 # Quotate Italia (cotizadas)

    # Reino Unido
    "https://www.ft.com/markets?format=rss",                                       # Financial Times Markets

    # Alemania
    "https://www.handelsblatt.com/contentexport/feed/finanzen",                    # Handelsblatt Finanzen

    # Pan-europeos / globales
    "https://es.investing.com/rss/news.rss",                                       # Investing.com Noticias (en español)
    "https://www.euronext.com/en/rss",                                             # Euronext (bolsas FR, NL, BE, etc.)
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

def send_telegram(msg, is_suspect=False):
    if not BOT_TOKEN or not CHAT_ID:
        print("Error: BOT_TOKEN o CHAT_ID no configurados.")
        return
    prefix = "⚠️ *Posible OPA – revisar*" if is_suspect else "🚨 *¡OPA Detectada!*"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": f"{prefix}\n\n{msg}",
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
    if any(pattern in text_lower for pattern in EXCLUDE_PATTERNS):
        print(f"Excluido: {text_lower[:100]}...")
        return False, False
    
    has_strong = any(kw.lower() in text_lower for kw in STRONG_KEYWORDS)
    has_secondary = any(kw.lower() in text_lower for kw in SECONDARY_KEYWORDS)
    
    if has_strong:
        print(f"OPA fuerte: {text_lower[:100]}...")
        return True, False
    elif has_secondary:
        print(f"OPA sospechosa: {text_lower[:100]}...")
        return True, True
    else:
        print(f"No OPA: {text_lower[:100]}...")
        return False, False

def check_rss():
    seen = load_seen()
    new_alerts = 0
    
    for feed_url in RSS_FEEDS:
        print(f"Procesando RSS: {feed_url}")
        try:
            feed = feedparser.parse(feed_url, agent="OPA-Bot/1.0")
            if feed.bozo:
                print(f"  Problema feed: {feed.bozo_exception}")
                continue
            
            for entry in feed.entries:
                link = entry.get('link', '')
                if not link: continue
                
                clean_link = normalize_url(link)
                clean_title = re.sub(r'\s+', ' ', entry.title.strip()) if entry.title else ''
                uid_input = clean_link + clean_title
                uid = hashlib.md5(uid_input.encode('utf-8')).hexdigest()
                
                if uid in seen: continue
                
                text = (
                    entry.get('title', '') + " " +
                    entry.get('summary', '') + " " +
                    entry.get('description', '')
                )
                
                is_detected, is_suspect = is_opa(text)
                if is_detected:
                    pub_time = entry.get('published', datetime.now().strftime('%Y-%m-%d %H:%M'))
                    source = feed.feed.get('title', feed_url.split('//')[-1].split('/')[0])
                    
                    msg = (
                        f"**Título:** {entry.title}\n"
                        f"**Fuente:** {source}\n"
                        f"**Publicado:** {pub_time}\n"
                        f"**Alerta:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                        f"[Leer]({link})"
                    )
                    send_telegram(msg, is_suspect)
                    seen.add(uid)
                    new_alerts += 1
        except Exception as e:
            print(f"Error en {feed_url}: {e}")
    
    save_seen(seen)
    return new_alerts, seen

# ... (aquí mantén tu función check_oir_page() actualizada con la versión robusta que te di antes, la de líneas con regex para markdown)

if __name__ == "__main__":
    print("Iniciando chequeo completo...")
    alerts_rss, _ = check_rss()
    check_oir_page()  # Mantén esta llamada para el scraping de la página OIR
    print(f"Finalizado. Alertas nuevas totales: {alerts_rss} (más posibles de OIR)")
