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
    "opa obligatoria", "obligatoria sobre",  # Añadidas específicas CNMV
]

# Keywords secundarias (títulos genéricos de CNMV)
SECONDARY_KEYWORDS = [
    "ofertas públicas de adquisición", "oferta pública", "adquisición de acciones",
    "ofertas públicas", "opa sobre", "adquisición obligatoria", "compra de acciones"
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
    # ... resto de feeds internacionales ...
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
    prefix = "⚠️ *Posible OPA – revisar manualmente*" if is_suspect else "🚨 *¡OPA Detectada!*"
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
    
    # Excluir falsos positivos
    if any(pattern in text_lower for pattern in EXCLUDE_PATTERNS):
        print(f"Excluido por patrón: {text_lower[:100]}...")
        return False, False
    
    has_strong = any(kw.lower() in text_lower for kw in STRONG_KEYWORDS)
    has_secondary = any(kw.lower() in text_lower for kw in SECONDARY_KEYWORDS)
    
    if has_strong:
        print(f"OPA fuerte detectada: {text_lower[:100]}...")
        return True, False
    elif has_secondary:
        print(f"OPA secundaria/sospechosa: {text_lower[:100]}...")
        return True, True  # True = OPA, True = es sospechosa (enviar con aviso)
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
    return new_alerts, seen  # devolvemos seen para usarlo en OIR

def check_oir_page():
    url = "https://www.cnmv.es/portal/otra-informacion-relevante/aldia-oir?lang=es"
    headers = {"User-Agent": "OPA-Bot/1.0 +https://github.com/elpa82-dev/opa-alerts-bot"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Selector amplio: busca párrafos o elementos que contengan hora + enlaces
        # Ajusta según inspección real (DevTools → inspecciona un anuncio)
        announcements = soup.select("p, div.content p, .fecha + p")  # prueba estos
        
        seen = load_seen()  # recargamos por si rss ya añadió
        
        for item in announcements[:15]:  # limitamos a últimos ~15 para eficiencia
            text = item.get_text(strip=True, separator=" ")
            if not text or len(text) < 30: continue
            
            # Intentamos extraer hora, emisor, título
            hora_match = re.search(r'(\d{2}:\d{2})', text)
            hora = hora_match.group(1) if hora_match else "??:??"
            
            links = item.find_all("a")
            emisor = ""
            titulo = ""
            link = ""
            
            if len(links) >= 1:
                emisor = links[0].get_text(strip=True)
            if len(links) >= 2:
                titulo = links[1].get_text(strip=True)
                link = links[1].get("href", "")
                if link and not link.startswith("http"):
                    link = "https://www.cnmv.es" + link
            
            combined_text = f"{hora} {emisor} {titulo}"
            uid = hashlib.md5((link + titulo).encode('utf-8')).hexdigest()
            
            if uid in seen: continue
            
            is_detected, is_suspect = is_opa(combined_text)
            if is_detected:
                msg = (
                    f"**Hora:** {hora}\n"
                    f"**Emisor:** {emisor}\n"
                    f"**Título:** {titulo}\n"
                    f"**Fuente:** CNMV OIR\n"
                    f"**Alerta:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"[Ver documento]({link})"
                )
                send_telegram(msg, is_suspect)
                seen.add(uid)
        
        save_seen(seen)
        print("Scraping OIR completado.")
    except Exception as e:
        print(f"Error scraping OIR: {e}")

if __name__ == "__main__":
    print("Iniciando chequeo completo...")
    alerts_rss, _ = check_rss()
    check_oir_page()  # ejecutamos después del RSS
    print(f"Finalizado. Alertas nuevas totales: {alerts_rss} (más posibles de OIR)")
