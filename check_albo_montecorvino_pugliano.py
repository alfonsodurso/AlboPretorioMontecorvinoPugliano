import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import json
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

# --- NOTIFICA TELEGRAM ---
def send_telegram_notification(message, chat_id=TELEGRAM_CHAT_ID):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
    try:
        r = requests.post(url, data=payload)
        r.raise_for_status()
        if r.json().get('ok'):
            print("✅ Messaggio inviato.")
        else:
            print(f"❌ Telegram API: {r.json().get('description')}")
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}")

# --- CONTROLLO NUOVE PUBBLICAZIONI ---
def check_for_new_publications():
    processed_data = get_gist_data()
    processed_ids = set(processed_data.keys())
    new_publications = []

    try:
        response = requests.get(START_URL, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        rows = soup.select('table.master-detail-list-table tr.master-detail-list-line')
        for row in rows:
            act_id = row.get('data-id')
            if not act_id or act_id in processed_ids:
                continue
            cells = row.find_all('td')
            if len(cells) >= 5:
                numero_atto = cells[0].get_text(strip=True)
                tipo_atto = cells[1].get_text(strip=True)
                oggetto = cells[2].get_text(strip=True)
                date_parts = cells[3].get_text(separator=' ', strip=True).split()
                data_inizio = date_parts[0] if date_parts else ''
                data_fine = date_parts[1] if len(date_parts) > 1 else ''
                detail_link_tag = cells[4].find('a', title='Apri Dettaglio')
                url_dettaglio = urljoin(BASE_URL, detail_link_tag['href']) if detail_link_tag else ''
                publication = {
                    'id': act_id,
                    'numero': numero_atto,
                    'tipo': tipo_atto,
                    'oggetto': oggetto,
                    'data_inizio': data_inizio,
                    'data_fine': data_fine,
                    'url_dettaglio': url_dettaglio
                }
                new_publications.append(publication)
                processed_data[act_id] = publication
    except Exception as e:
        send_telegram_notification(f"❌ Errore durante il controllo nuove pubblicazioni: {e}")

    if new_publications:
        for pub in new_publications:
            message = (
                f"📰 *Nuova Pubblicazione*\n\n"
                f"🔢 *Numero:* {pub['numero']}\n"
                f"🗂 *Tipo:* {pub['tipo']}\n"
                f"📅 *Periodo:* {pub.get('data_inizio','')} - {pub.get('data_fine','')}\n"
                f"📝 {pub['oggetto']}\n"
                f"🔗 [Dettagli]({pub['url_dettaglio']})"
            )
            send_telegram_notification(message)
        update_gist_data(processed_data)
    else:
        print("Nessuna nuova pubblicazione trovata.")
    return processed_data

# --- ASSISTENTE INTELLIGENTE ---
def ask_assistant(question, publications, gemini_api_key=GEMINI_API_KEY):
    if not gemini_api_key:
        return "Chiave Gemini non configurata."

    if not publications:
        return "Nessuna pubblicazione disponibile al momento."

    context = "\n".join([f"{p['numero']} - {p['tipo']} - {p['oggetto']} - Link: {p.get('url_dettaglio','')}" 
                         for p in publications.values()])

    prompt = f"""
Sei un assistente virtuale specializzato nelle pubblicazioni del Comune di Montecorvino Pugliano.
Leggi i seguenti dati delle pubblicazioni:

{context}

Rispondi alla seguente domanda dell'utente in modo chiaro e sintetico:

Domanda: {question}
"""
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ Errore Gemini: {e}")
        return "Errore durante la generazione della risposta."

# --- GESTIONE COMANDO TELEGRAM /assistente ---
def handle_assistant_command(command_text, publications):
    if command_text.startswith("/assistente "):
        domanda = command_text[len("/assistente "):].strip()
        if not domanda:
            return "Inserisci una domanda dopo il comando /assistente."
        risposta = ask_assistant(domanda, publications)
        return risposta
    else:
        return "Comando non riconosciuto. Usa /assistente <domanda>"

# --- ESECUZIONE ---
if __name__ == "__main__":
    # 1. Controllo nuove pubblicazioni
    processed_data = check_for_new_publications()

    # 2. Gestione comando simulato /assistente
    # In produzione, qui leggeresti l'input reale da Telegram
    comando_utente = "/assistente Quali pubblicazioni parlano di aste?"
    risposta = handle_assistant_command(comando_utente, processed_data)
    send_telegram_notification(risposta)
