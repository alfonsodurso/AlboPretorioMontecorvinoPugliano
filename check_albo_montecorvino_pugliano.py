# check_albo_montecorvino_pugliano.py
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import json
import re
import pdfplumber
import io
import pytesseract
from pdf2image import convert_from_bytes
import google.generativeai as genai

# --- CONFIGURAZIONE ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GIST_ID = os.getenv('GIST_ID')
GIST_SECRET_TOKEN = os.getenv('GIST_SECRET_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

GIST_FILENAME = 'processed_data_montecorvino.json'

BASE_URL = "https://montecorvinopugliano.trasparenza-valutazione-merito.it/"
START_URL = "https://montecorvinopugliano.trasparenza-valutazione-merito.it/web/trasparenza/papca-ap/-/papca/igrid/1173286/25141"
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# --- FUNZIONI GIST ---
def get_gist_data():
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/gists/{GIST_ID}'
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        gist_data = response.json()
        if GIST_FILENAME in gist_data['files']:
            content = gist_data['files'][GIST_FILENAME]['content']
            if content.strip():
                return json.loads(content)
        return {}
    except Exception as e:
        print(f"❌ Errore recupero Gist: {e}")
        return {}

def update_gist_data(data):
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/gists/{GIST_ID}'
    payload = {'files': {GIST_FILENAME: {'content': json.dumps(data, indent=4)}}}
    try:
        response = requests.patch(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        print("✅ Gist aggiornato con successo.")
    except Exception as e:
        print(f"❌ Errore aggiornamento Gist: {e}")

# --- ESTRAZIONE TESTO PDF (pdfplumber + OCR) ---
def estrai_testo_pdf(pdf_url):
    if not pdf_url:
        return "Nessun PDF trovato."
    try:
        response = requests.get(pdf_url, headers=HEADERS, stream=True)
        response.raise_for_status()
        pdf_bytes = response.content

        testo = ""
        # 1. Proviamo pdfplumber
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    testo += page.extract_text() or ""
        except Exception as e:
            print(f"[!] pdfplumber errore: {e}")

        # 2. Se testo troppo breve, facciamo OCR
        if len(testo.strip()) < 100:
            try:
                pagine = convert_from_bytes(pdf_bytes)
                testo = ""
                for pagina in pagine:
                    testo += pytesseract.image_to_string(pagina, lang="ita") + "\n"
            except Exception as e:
                print(f"[!] OCR errore: {e}")

        testo = re.sub(r'\s+', ' ', testo).strip()
        print(f"📄 Testo estratto ({len(testo)} caratteri)")
        return testo or "Testo non disponibile."
    except Exception as e:
        print(f"❌ Errore scarico/processo PDF: {e}")
        return "Errore estrazione PDF."

# --- RIASSUNTO CON GEMINI ---
def summarize_text_with_gemini(text):
    if not GEMINI_API_KEY:
        return "Chiave API Gemini non configurata."
    if not text or len(text) < 100:
        return "Testo troppo breve o non disponibile per il riassunto."

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        prompt = f"Riassumi il seguente documento ufficiale del comune, in italiano. Il riassunto deve essere conciso, chiaro, evidenziando i punti principali. Max 1500 caratteri:\n\n{text}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ Errore API Gemini: {e}")
        return "Errore nella generazione del riassunto."

# --- NOTIFICA TELEGRAM ---
def send_telegram_notification(publication):
    periodo = publication['data_inizio']
    if publication.get('data_fine'):
        periodo += f" - {publication['data_fine']}"

    message = (
        f"🔔 *Nuova Pubblicazione*\n"
        f"*Tipo Atto:* {publication['tipo']}\n"
        f"*Numero:* {publication['numero']}\n"
        f"*Periodo pubblicazione:* {periodo}\n"
        f"*Oggetto:* {publication['oggetto']}\n"
        f"[Vedi Dettagli]({publication['url_dettaglio']})\n\n"
        f"📝 *Riassunto:*\n{publication.get('riassunto', 'Non disponibile.')}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
    try:
        r = requests.post(url, data=payload)
        r.raise_for_status()
        if r.json().get('ok'):
            print(f"✅ Notifica inviata per atto {publication['numero']}")
        else:
            print(f"❌ Telegram API: {r.json().get('description')}")
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}")

# --- SUPPORTO PDF DETTAGLIO ---
def get_pdf_link_from_detail_page(url_dettaglio):
    try:
        r = requests.get(url_dettaglio, headers=HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')
        tag = soup.find('a', href=re.compile(r'\.pdf$', re.I))
        if tag:
            return urljoin(BASE_URL, tag['href'])
    except Exception as e:
        print(f"❌ Errore PDF link: {e}")
    return None

# --- MAIN ---
def check_for_new_publications():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GIST_ID, GIST_SECRET_TOKEN, GEMINI_API_KEY]):
        print("❌ Credenziali mancanti.")
        return

    processed_data = get_gist_data()
    processed_ids = set(processed_data.keys())
    print(f"Caricati {len(processed_ids)} atti già processati.")

    new_publications = []
    current_url = START_URL
    page_num = 1

    while current_url:
        print(f"--- Pagina {page_num} ---")
        try:
            r = requests.get(current_url, headers=HEADERS)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'lxml')
        except Exception as e:
            print(f"Errore scarico pagina: {e}")
            break

        rows = soup.select('table.master-detail-list-table tr.master-detail-list-line')
        if not rows:
            print("Nessuna riga trovata.")
            break

        for row in rows:
            act_id = row.get('data-id')
            if not act_id or act_id in processed_ids:
                continue

            cells = row.find_all('td')
            if len(cells) >= 5:
                numero = cells[0].get_text(strip=True)
                tipo = cells[1].get_text(strip=True)
                oggetto = cells[2].get_text(strip=True)
                date_parts = cells[3].get_text(strip=True).split()
                data_inizio = date_parts[0] if date_parts else ''
                data_fine = date_parts[1] if len(date_parts) > 1 else ''
                detail_link_tag = cells[4].find('a', title='Apri Dettaglio')
                url_dettaglio = urljoin(BASE_URL, detail_link_tag['href']) if detail_link_tag else ''

                pdf_url = get_pdf_link_from_detail_page(url_dettaglio)
                testo_pdf = estrai_testo_pdf(pdf_url)
                summary = summarize_text_with_gemini(testo_pdf)

                pub = {
                    'id': act_id,
                    'numero': numero,
                    'tipo': tipo,
                    'oggetto': oggetto,
                    'data_inizio': data_inizio,
                    'data_fine': data_fine,
                    'url_dettaglio': url_dettaglio,
                    'riassunto': summary
                }

                new_publications.append(pub)
                processed_data[act_id] = {
                    'numero': numero,
                    'oggetto': oggetto,
                    'riassunto': summary
                }

        # paginazione
        pagination_ul = soup.select_one('div.pagination ul')
        next_page_link = None
        if pagination_ul:
            next_tag = pagination_ul.find(lambda tag: tag.name == 'a' and 'Avanti' in tag.get_text() and 'disabled' not in tag.find_parent('li').get('class', []))
            if next_tag:
                next_page_link = next_tag.get('href')

        if next_page_link:
            current_url = urljoin(BASE_URL, next_page_link)
            page_num += 1
            time.sleep(1)
        else:
            current_url = None

    if not new_publications:
        print("Nessuna nuova pubblicazione trovata in totale.")
    else:
        print(f"\nTrovati {len(new_publications)} nuovi atti in totale. Invio notifiche...")
        for publication in reversed(new_publications):
            send_telegram_notification(publication)
            time.sleep(2)

        # Aggiorniamo il Gist una sola volta alla fine
        update_gist_data(processed_data)

    print("--- Controllo terminato ---")

if __name__ == "__main__":
    check_for_new_publications()

