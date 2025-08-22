import os
import requests
import time
import json
import google.generativeai as genai

# --- CONFIGURAZIONE ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GIST_ID = os.getenv('GIST_ID')
GIST_SECRET_TOKEN = os.getenv('GIST_SECRET_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

GIST_FILENAME = 'processed_data_montecorvino.json'
POLL_INTERVAL = 3  # secondi tra un controllo e l'altro

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

# --- TELEGRAM ---
def send_telegram_message(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
    try:
        r = requests.post(url, data=payload)
        r.raise_for_status()
        if r.json().get('ok'):
            print(f"✅ Risposta inviata a chat {chat_id}")
        else:
            print(f"❌ Telegram API: {r.json().get('description')}")
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}")

# --- ASSISTENTE GEMINI ---
def ask_assistant(question, publications):
    if not GEMINI_API_KEY:
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
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ Errore Gemini: {e}")
        return "Errore durante la generazione della risposta."

# --- GESTIONE COMANDO ---
def handle_command(message, publications):
    text = message.get('text', '')
    chat_id = message['chat']['id']

    if text.startswith("/assistente"):
        domanda = text[len("/assistente"):].strip()
        if not domanda:
            send_telegram_message(chat_id, "Inserisci una domanda dopo il comando /assistente.\nEsempio: /assistente Quali pubblicazioni parlano di aste?")
            return
        risposta = ask_assistant(domanda, publications)
        send_telegram_message(chat_id, risposta)

# --- LONG POLLING ---
def run_bot():
    print("🤖 Bot Telegram in ascolto dei comandi...")
    offset = None
    publications = get_gist_data()

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {'timeout': 100, 'offset': offset}
            response = requests.get(url, params=params, timeout=120)
            response.raise_for_status()
            data = response.json()
            if not data.get('ok'):
                time.sleep(POLL_INTERVAL)
                continue
            updates = data.get('result', [])
            for update in updates:
                offset = update['update_id'] + 1
                if 'message' in update:
                    handle_command(update['message'], publications)
        except Exception as e:
            print(f"❌ Errore long polling: {e}")
            time.sleep(POLL_INTERVAL)

# --- MAIN ---
if __name__ == "__main__":
    run_bot()
