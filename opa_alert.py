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
    # Originales en inglés / generales
    "remain vulnerable", "treacherous calm", "trendzicht", "trend monitor", "trend monitor 2026",
    "financial markets remain", "markets remain", "vulnerable", "geopolitical tensions", "hyper-personalisation",
    
    # Español (muy común en CNMV, BME, Expansión, Cinco Días, El Economista)
    "recompra de acciones",
    "programa de recompra",
    "programas de recompra",
    "recompra de acciones propias",
    "autocartera",
    "ampliación del programa de recompra",
    "ejecución de recompra",
    "comunicación de recompra",
    "recompra y amortización",
    "reducción de capital mediante recompra",
    "operaciones de autocartera",
    "compra de acciones propias",
    
    # Inglés (Financial Times, Investing.com, Euronext, etc.)
    "share buyback",
    "share repurchase",
    "stock buyback",
    "share repurchase program",
    "buyback program",
    "repurchase of shares",
    "own shares purchase",
    "treasury shares",
    
    # Francés (Les Echos, AMF, Euronext Francia)
    "rachat d'actions",
    "programme de rachat d'actions",
    "rachats d'actions",
    "autocontrôle",
    "actions propres",
    "programme de rachat",
    
    # Italiano (Il Sole 24 Ore, CONSOB)
    "riacquisto azioni",
    "programma di riacquisto azioni",
    "autoconservazione",
    "azioni proprie",
    "buyback azionario",
    "programma di buyback",
    
    # Alemán (Handelsblatt, BaFin)
    "aktienrückkauf",
    "rückkaufprogramm",
    "aktienrückkaufprogramm",
    "eigenbestandsaktien",
    "rückkauf von aktien",
    "aktienrückkaufprogramm",
    
    # Otras exclusiones útiles (boletines, ruido común)
    "boletin diario", "boletín diario", "mtf equity", "clehrp", "indexa capital", "estructuras",
    "dividendo", "ampliación de capital", "resultados trimestrales", "situación financiera"
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

def check_oir_page():
    url = "https://www.cnmv.es/portal/otra-informacion-relevante/aldia-oir?lang=es"
    headers = {"User-Agent": "OPA-Bot/1.0 (+tu-email-o-github si quieres)"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        text_content = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text_content.split("\n") if line.strip() and len(line.strip()) > 5]
        
        seen = load_seen()
        i = 0
        current_date = ""
        processed_entries = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Fecha (más flexible: acepta ## o sin #)
            date_match = re.match(r'^(##?|\*{1,2})\s*(\d{2}/\d{2}/\d{4}.*)', line)
            if date_match:
                current_date = date_match.group(2).strip()
                i += 1
                continue
            
            # Línea de hora: * * HH:MM o variaciones (a veces + * o solo * HH:MM)
            hora_match = re.match(r'^[\*\+]{1,2}\s*[\*\+]?\s*(\d{2}:\d{2})', line)
            if hora_match:
                hora = hora_match.group(1)
                processed_entries += 1
                
                # Línea emisor
                i += 1
                if i >= len(lines): break
                emisor_line = lines[i]
                emisor_match = re.search(r'[\*\+]{1,2}\s*\[([^\]]+)\]', emisor_line)
                emisor = emisor_match.group(1).strip() if emisor_match else ""
                
                # Línea tipo
                i += 1
                if i >= len(lines): break
                tipo_line = lines[i]
                tipo_match = re.search(r'^[\*\+]{1,2}\s*(.+?)(?:\s*\[|$)', tipo_line)
                tipo = tipo_match.group(1).strip() if tipo_match else tipo_line.lstrip('*+ ').strip()
                
                # Línea detalle + link
                i += 1
                if i >= len(lines): break
                detalle_line = lines[i]
                titulo_match = re.search(r'[\*\+]{1,2}\s*\[([^\]]+)\]', detalle_line)
                titulo = titulo_match.group(1).strip() if titulo_match else ""
                
                link_match = re.search(r'\((https?://[^\)]+|/[^\)]+)\)', detalle_line)
                link = link_match.group(1) if link_match else ""
                if link and not link.startswith('http'):
                    link = "https://www.cnmv.es" + link
                
                combined_text = f"{current_date} {hora} {emisor} {tipo} {titulo}".lower()
                
                if len(combined_text) < 40 or not hora or not titulo:
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
                        f"**Fuente:** CNMV OIR (página)\n"
                        f"**Alerta:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                        f"[Ver documento]({link})"
                    )
                    send_telegram(msg)
                    seen.add(uid)
                    print(f"OPA detectada y enviada: {titulo[:80]}...")
                
                i += 1
                continue
            
            i += 1
        
        save_seen(seen)
        print(f"Scraping OIR completado. Entradas procesadas: {processed_entries}")
    
    except Exception as e:
        print(f"Error scraping OIR: {type(e).__name__}: {e}")
        
if __name__ == "__main__":
    print("Iniciando chequeo completo...")
    alerts_rss, _ = check_rss()
    check_oir_page()  # Mantén esta llamada para el scraping de la página OIR
    print(f"Finalizado. Alertas nuevas totales: {alerts_rss} (más posibles de OIR)")
