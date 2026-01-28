import requests
import feedparser
import hashlib
import json
import os
from datetime import datetime

# Cargar desde variables de entorno (configúralas en GitHub Secrets o en tu entorno local)
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
DB_FILE = "seen.json"

# Palabras clave expandidas para OPA/ofertas de adquisición en toda Europa (insensible a mayúsculas)
KEYWORDS = [
    # Español (originales + variaciones)
    "opa",
    "oferta pública de adquisición",
    "oferta publica de adquisicion",
    "oferta de exclusión",
    
    # Inglés (originales + comunes en UE/UK)
    "tender offer",
    "takeover",
    "takeover bid",
    "public takeover",
    "cash offer",
    "voluntary offer",
    "mandatory offer",
    "squeeze-out",
    
    # Francés (Francia, Bélgica, Luxemburgo)
    "offre publique d'achat",
    "offre publique obligatoire",
    "opa obligatoire",
    
    # Italiano (Italia)
    "offerta pubblica di acquisto",
    "opa obbligatoria",
    
    # Alemán (Alemania, Austria)
    "übernahmeangebot",
    "pflichtangebot",
    "öffentliches übernahmeangebot",
    
    # Neerlandés (Países Bajos, Bélgica)
    "openbaar bod",
    "openbaar overnamebod",
    "verplicht bod",
    
    # Sueco (Suecia)
    "offentligt uppköpserbjudande",
    "obligatoriskt bud",
    
    # Portugués (Portugal)
    "oferta pública de aquisição",  # Similar al español, pero con acentos
    "opa obrigatória",
    
    # Polaco (Polonia)
    "publiczna oferta przejęcia",
    "obowiązkowa oferta",
    
    # Otros comunes en UE (griego, danés, etc., pero prioricé mayoritarios)
    "offentlig overtagelsestilbud",  # Danés
    "julkisen ostotarjouksen"       # Finlandés (parcial)
]

# Feeds RSS relevantes (enfocados en toda Europa: reguladores, bolsas y noticias financieras)
RSS_FEEDS = [
    # España (originales)
    "https://www.cnmv.es/portal/RSS/RssHandler.ashx?fac=HECHOSRELEV",  # CNMV (OPAs oficiales)
    "https://www.bolsamadrid.es/rss/RSS.ashx?feed=Todo",  # Bolsa de Madrid
    "https://www.expansion.com/rss/mercados.xml",  # Expansion
    "https://www.cincodias.com/rss/mercados",  # Cinco Días
    
    # Francia (original)
    "https://www.amf-france.org/en/rss",  # AMF
    
    # Italia (original)
    "https://www.consob.it/web/consob-and-its-activities/rss",  # CONSOB
    
    # UK
    "https://www.fca.org.uk/rss/news",  # FCA (noticias y anuncios de mercados)
    
    # Alemania
    "https://www.bafin.de/EN/Service/RSS/rss_artikel_en.html",  # BaFin (noticias y supervisión)
    
    # Países Bajos
    "https://www.afm.nl/en/rss",  # AFM (noticias financieras)
    
    # Suecia
    "https://www.fi.se/en/rss/",  # Finansinspektionen (FI, noticias y anuncios)
    
    # Portugal
    "https://www.cmvm.pt/en/rss",  # CMVM (alertas y noticias)
    
    # Polonia
    "https://www.knf.gov.pl/en/rss",  # KNF (noticias regulatorias)
    
    # Paneuropeos
    "https://www.ecb.europa.eu/home/html/rss.en.html",  # ECB (Banco Central Europeo, incluye finanzas)
    "https://www.esma.europa.eu/rss",  # ESMA (Autoridad Europea de Valores, clave para OPAs UE)
    "https://www.euronext.com/en/rss",  # Euronext (bolsas en varios países: Francia, Países Bajos, etc.)
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
    
    # Excluir frases comunes de "mercado sin cambios" o placeholders
    exclude_patterns = [
        "thesaurus financial markets remain unchanged",
        "mercados financieros permanecen inalterados",
        "mercados sin cambios",
        "remain unchanged",
        "permanecen inalterados",
        "sin variación", "sin cambios significativos"
    ]
    
    if any(pattern in text for pattern in exclude_patterns):
        return False
    
    # Solo aceptar si hay al menos una keyword FUERTE (evita coincidencias débiles)
    strong_keywords = [
        "opa", 
        "oferta pública de adquisición", 
        "oferta publica de adquisicion",
        "tender offer", 
        "takeover bid", 
        "mandatory offer", 
        "offre publique d'achat", 
        "offerta pubblica di acquisto", 
        "übernahmeangebot",
        # Puedes añadir más de tu lista original si quieres
    ]
    
    return any(k.lower() in text for k in strong_keywords)

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
