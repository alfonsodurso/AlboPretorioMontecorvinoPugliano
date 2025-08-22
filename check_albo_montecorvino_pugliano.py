# check_albo_montecorvino_pugliano.py (versione V9 - con Gemini)
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
import os
import json
import pdfplumber
import google.generativeai as genai
import re

# --- CONFIGURAZIONE ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GIST_ID = os.getenv('GIST_ID')
GIST_SECRET_TOKEN = os.getenv('GIST_SECRET_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') # Nuova variabile per la chiave API di Gemini

# Cambiamo il nome del file per passare a un formato JSON più strutturato
GIST_FILENAME = 'processed_data_montecorvino.json'

# --- URL STABILI ---
BASE_URL = "[https://montecorvinopugliano.trasparenza-valutazione-merito.it/](https://montecorvinopugliano.trasparenza-valutazione-merito.it/)"
START_URL = "[https://montecorvinopugliano.trasparenza-valutazione-merito.it/web/trasparenza/papca-ap/-/papca/igrid/1173286/25141](https://montecorvinopugliano.trasparenza-valutazione-merito.it/web/trasparenza/papca-ap/-/papca/igrid/1173286/25141)"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}


# --- FUNZIONI PER GIST (modificate per JSON) ---
def get_gist_data():
    """Recupera il contenuto JSON dal Gist. Restituisce un dizionario."""
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'[https://api.github.com/gists/](https://api.github.com/gists/){GIST_ID}'
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
        print(f"❌ Errore nel recuperare il Gist o nel parsare il JSON: {e}. Parto con un dizionario vuoto.")
        return {}

def update_gist_data(data):
    """Aggiorna il contenuto JSON nel Gist."""
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'[https://api.github.com/gists/](https://api.github.com/gists/){GIST_ID}'
    payload = {'files': {GIST_FILENAME: {'content': json.dumps(data, indent=4)}}}
    try:
        response = requests.patch(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        print("✅ Gist aggiornato con successo.")
    except Exception as e:
        print(f"❌ Errore nell'aggiornare il Gist: {e}")

# --- NUOVE FUNZIONI PER IL RIASSUNTO ---
def get_pdf_link_from_detail_page(url_dettaglio):
    """Trova il link del PDF sulla pagina di dettaglio."""
    try:
        response = requests.get(url_dettaglio, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        # Cerca il tag <a> che contiene un link a un file .pdf
        pdf_link_tag = soup.find('a', href=re.compile(r'\.pdf$', re.I))
        if pdf_link_tag:
            return urljoin(BASE_URL, pdf_link_tag['href'])
    except Exception as e:
        print(f"❌ Errore nel trovare il link PDF: {e}")
    return None

def download_and_extract_text(pdf_url):
    """Scarica il PDF e ne estrae il testo."""
    if not pdf_url:
        return "Nessun file PDF allegato trovato."
    
    try:
        print(f"🔎 Scarico e analizzo il PDF da: {pdf_url}")
        response = requests.get(pdf_url, headers=HEADERS, stream=True)
        response.raise_for_status()
        
        pdf_content = response.content
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() or ""
            # Pulisci il testo da spazi multipli e caratteri di formattazione non necessari
            text = re.sub(r'\s+', ' ', text).strip()
            return text
    except Exception as e:
        print(f"❌ Errore nel processare il PDF: {e}")
        return "Errore nell'estrazione del testo dal PDF."

def summarize_text_with_gemini(text):
    """Riassume il testo usando l'API di Gemini."""
    if not GEMINI_API_KEY:
        return "Chiave API di Gemini non configurata."
    if not text or len(text) < 100:
        return "Testo troppo breve o non disponibile per il riassunto."

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        prompt = f"Riassumi il seguente documento ufficiale del comune, in italiano. Il riassunto deve essere conciso, chiaro, e deve evidenziare i punti più importanti. Max 1500 caratteri:\n\n{text}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ Errore nell'API di Gemini: {e}")
        return "Errore nella generazione del riassunto."

# --- FUNZIONE DI NOTIFICA TELEGRAM (modificata) ---
def send_telegram_notification(publication):
    """Invia una notifica tramite il bot di Telegram con il riassunto."""
    periodo_pubblicazione = publication['data_inizio']
    if publication['data_fine']:
        periodo_pubblicazione += f" - {publication['data_fine']}"

    message_parts = [
        f"🔔 *Nuova Pubblicazione*",
        f"\n*Tipo Atto:* {publication['tipo']}",
        f"*Numero:* {publication['numero']}",
        f"*Periodo pubblicazione:* {periodo_pubblicazione}",
        f"\n*Oggetto:* {publication['oggetto']}",
        f"\n[Vedi Dettagli e Allegati]({publication['url_dettaglio']})",
        f"\n\n📝 *Riassunto:*\n{publication.get('riassunto', 'Non disponibile.')}"
    ]
    final_message = "\n".join(message_parts)
    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': final_message, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        if response.json().get('ok'):
            print(f"✅ Notifica inviata per l'atto n. {publication['numero']}")
        else:
            print(f"❌ Errore API Telegram: {response.json().get('description')}")
    except Exception as e:
        print(f"❌ Eccezione durante l'invio della notifica: {e}")

# --- FUNZIONE PRINCIPALE (modificata) ---
def check_for_new_publications():
    """Funzione principale che controlla, confronta, genera riassunti e notifica."""
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GIST_ID, GIST_SECRET_TOKEN, GEMINI_API_KEY]):
        print("❌ ERRORE: Una o più credenziali (Secrets) non sono state impostate.")
        return

    print("--- Avvio controllo nuove pubblicazioni (Montecorvino Pugliano) ---")
    
    # Leggiamo i dati dal Gist in formato JSON
    processed_data = get_gist_data()
    processed_ids = set(processed_data.keys())
    print(f"Caricati {len(processed_ids)} ID già processati dal Gist.")

    new_publications_to_notify = []
    current_page_url = START_URL
    page_num = 1

    while current_page_url:
        print(f"--- Analizzo la Pagina {page_num} ---")
        try:
            response = requests.get(current_page_url, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
        except requests.exceptions.RequestException as e:
            print(f"Errore: Impossibile scaricare la pagina {page_num}. {e}")
            break

        rows = soup.select('table.master-detail-list-table tr.master-detail-list-line')
        if not rows:
            print("Nessuna riga trovata in questa pagina. Interruzione.")
            break

        for row in rows:
            act_id = row.get('data-id')
            if not act_id or act_id in processed_ids:
                continue

            print(f"TROVATO NUOVO ATTO! ID: {act_id}")
            cells = row.find_all('td')
            if len(cells) >= 5:
                # Estrazione dati
                numero_atto = cells[0].get_text(strip=True)
                tipo_atto = ' '.join(cells[1].get_text(strip=True).split())
                oggetto = cells[2].get_text(strip=True)
                date_parts = cells[3].get_text(separator=' ', strip=True).split()
                data_inizio = date_parts[0] if date_parts else ''
                data_fine = date_parts[1] if len(date_parts) > 1 else ''
                detail_link_tag = cells[4].find('a', title='Apri Dettaglio')
                url_dettaglio = urljoin(BASE_URL, detail_link_tag['href']) if detail_link_tag else ''

                # --- Nuova logica per il riassunto ---
                pdf_url = get_pdf_link_from_detail_page(url_dettaglio)
                pdf_text = download_and_extract_text(pdf_url)
                summary = summarize_text_with_gemini(pdf_text)
                
                # Creazione del dizionario per la notifica
                publication_details = {
                    'id': act_id,
                    'oggetto': oggetto,
                    'numero': numero_atto,
                    'tipo': tipo_atto,
                    'data_inizio': data_inizio,
                    'data_fine': data_fine,
                    'url_dettaglio': url_dettaglio,
                    'riassunto': summary
                }
                new_publications_to_notify.append(publication_details)
                
                # Aggiungiamo i dati della nuova pubblicazione al dizionario principale
                processed_data[act_id] = {
                    'oggetto': oggetto,
                    'numero': numero_atto,
                    'riassunto': summary
                }

        # Gestione paginazione
        pagination_ul = soup.select_one('div.pagination ul')
        next_page_link = None
        if pagination_ul:
            next_page_tag = pagination_ul.find(lambda tag: tag.name == 'a' and 'Avanti' in tag.get_text() and 'disabled' not in tag.find_parent('li').get('class', []))
            if next_page_tag:
                 next_page_link = next_page_tag

        if next_page_link and next_page_link.has_attr('href'):
            current_page_url = urljoin(BASE_URL, next_page_link['href'])
            page_num += 1
            time.sleep(1)
        else:
            print("Fine della paginazione.")
            current_page_url = None

    if not new_publications_to_notify:
        print("Nessuna nuova pubblicazione trovata in totale.")
    else:
        print(f"\nTrovati {len(new_publications_to_notify)} nuovi atti in totale. Invio notifiche...")
        for publication in reversed(new_publications_to_notify):
            send_telegram_notification(publication)
            time.sleep(2)
        
        # Aggiorniamo il Gist una sola volta alla fine con tutti i nuovi dati
        update_gist_data(processed_data)

    print("--- Controllo terminato ---")

if __name__ == "__main__":
    check_for_new_publications()

