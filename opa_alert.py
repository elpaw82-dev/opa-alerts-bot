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

# Solo keywords FUERTES → solo alerta real cuando aparezca "opa", "obligatoria", "autorizada", etc.
STRONG_KEYWORDS = [
    "opa", "opa obligatoria", "oferta pública de adquisición", "oferta publica de adquisicion",
    "tender offer", "takeover bid", "public takeover", "mandatory offer", "squeeze-out",
    "offre publique d'achat", "offre publique obligatoire", "opa obligatoire",
    "offerta pubblica di acquisto", "opa obbligatoria",
    "übernahmeangebot", "pflichtangebot", "öffentliches übernahmeangebot",
    "openbaar bod", "openbaar overnamebod", "verplicht bod",
    "offentligt uppköpserbjudande", "obligatoriskt bud",
    "oferta pública de aquisição", "opa obrigatória",
    "publiczna oferta przejęcia", "obowiązkowa oferta",
    "la cnmv informa que la opa", "autorizada", "formulada", "admitida a trámite",
    "solicitud de autorización", "opa sobre"
]

# Eliminamos SECONDARY_KEYWORDS para evitar falsos positivos
# SECONDARY_KEYWORDS = []  # Comentado / vacío

# Exclusiones reforzadas
EXCLUDE_PATTERNS = [
    "remain vulnerable", "treacherous calm", "trendzicht", "trend monitor", "trend monitor 2026",
    "financial markets remain", "mercados financieros permanecen", "permanecen inalterados",
    "markets remain", "vulnerable", "geopolitical tensions", "hyper-personalisation",
    "recompra de acciones", "autocartera", "programas de recompra", "boletin diario",
    "boletín diario", "mtf equity", "clehrp", "indexa capital", "estructuras", "sobre negocio",
    "situación financiera", "avance de ventas", "resultados", "dividendo"  # Añadidas comunes en boletines
]

RSS_FEEDS = [
    # Elimino el feed OIR inválido para evitar ruido en logs
    "https://www.cnmv.es/portal/RSS/RssHandler.ashx?fac=HECHOSRELEV",  # Prueba, aunque a veces falla
    "https://www.expansion.com/rss/mercados.xml",
    "https://www.cincodias.com/rss/mercados",
    "http://www.eleconomista.es/rss/rss-mercados.php",
    "https://www.bolsasymercados.es/bme-exchange/es/RSS/Regulacion",
    "https://www.bolsasymercados.es/MTF_Equity/esp/RSS/Boletin.ashx",
    "https://services.lesechos.fr/rss/les-echos-finance-marches.xml",
    "https://www.ilsole24ore.com/rss/finanza.xml",
    "https://www.ft.com/markets?format=rss",
    "https://www.handelsblatt.com/contentexport/feed/finanzen",
    "https://es.investing.com/rss/news.rss",
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
    prefix = "🚨 *¡OPA REAL Detectada!*"
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
        print(f"Excluido por patrón: {text_lower[:100]}...")
        return False
    
    has_strong = any(kw.lower() in text_lower for kw in STRONG_KEYWORDS)
    
    if has_strong:
        print(f"OPA detectada: {text_lower[:100]}...")
        return True
    else:
        print(f"No OPA: {text_lower[:100]}...")
        return False

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
                
                if is_opa(text):
                    pub_time = entry.get('published', datetime.now().strftime('%Y-%m-%d %H:%M'))
                    source = feed.feed.get('title', feed_url.split('//')[-1].split('/')[0])
                    
                    msg = (
                        f"**Título:** {entry.title}\n"
                        f"**Fuente:** {source}\n"
                        f"**Publicado:** {pub_time}\n"
                        f"**Alerta:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                        f"[Leer]({link})"
                    )
                    send_telegram(msg)
                    seen.add(uid)
                    new_alerts += 1
        except Exception as e:
            print(f"Error en {feed_url}: {e}")
    
    save_seen(seen)
    return new_alerts

# Función scraping OIR (versión ajustada al formato markdown-like real de la página)
def check_oir_page():
    url = "https://www.cnmv.es/portal/otra-informacion-relevante/aldia-oir?lang=es"
    headers = {"User-Agent": "OPA-Bot/1.0"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        text_content = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text_content.split("\n") if line.strip()]
        
        seen = load_seen()
        i = 0
        current_date = ""
        
        while i < len(lines):
            line = lines[i]
            
            # Fecha
            if re.match(r'^##?\s*\d{2}/\d{2}/\d{4}', line):
                current_date = line.lstrip('# ').strip()
                i += 1
                continue
            
            # Hora: * * HH:MM o + * HH:MM (variación observada)
            hora_match = re.match(r'^[\*\+]\s*[\*\+]\s*(\d{2}:\d{2})', line)
            if hora_match:
                hora = hora_match.group(1)
                
                i += 1
                if i >= len(lines): break
                emisor_line = lines[i]
                emisor_match = re.search(r'[\*\+]\s*\[([^\]]+)\]', emisor_line)
                emisor = emisor_match.group(1).strip() if emisor_match else ""
                
                i += 1
                if i >= len(lines): break
                tipo_line = lines[i]
                tipo_match = re.search(r'^[\*\+]\s*(.+)', tipo_line)
                tipo = tipo_match.group(1).strip() if tipo_match else ""
                
                i += 1
                if i >= len(lines): break
                detalle_line = lines[i]
                titulo_match = re.search(r'[\*\+]\s*\[([^\]]+)\]', detalle_line)
                titulo = titulo_match.group(1).strip() if titulo_match else ""
                
                link_match = re.search(r'\((https?://[^\)]+)\)', detalle_line)
                link = link_match.group(1) if link_match else ""
                if link and not link.startswith('http'):
                    link = "https://www.cnmv.es" + link
                
                combined_text = f"{current_date} {hora} {emisor} {tipo} {titulo}".lower()
                if len(combined_text) < 40 or not hora:
                    i += 1
                    continue
                
                uid = hashlib.md5((link + titulo).encode('utf-8')).hexdigest()
                if uid in seen:
                    i += 1
                    continue
                
                if is_opa(combined_text):
                    msg = (
                        f"**Fecha:** {current_date}\n"
                        f"**Hora:** {hora}\n"
                        f"**Emisor:** {emisor}\n"
                        f"**Tipo:** {tipo}\n"
                        f"**Detalle:** {titulo}\n"
                        f"**Fuente:** CNMV OIR\n\n"
                        f"[Ver]({link})"
                    )
                    send_telegram(msg)
                    seen.add(uid)
                
                i += 1
                continue
            
            i += 1
        
        save_seen(seen)
        print("OIR scraping OK")
    except Exception as e:
        print(f"Error OIR: {e}")

if __name__ == "__main__":
    print("Iniciando chequeo...")
    alerts_rss = check_rss()
    check_oir_page()
    print(f"Finalizado. Alertas RSS: {alerts_rss}")
