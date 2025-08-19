# check_albo_montecorvino_pugliano.py
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
import os
import json

# --- CONFIGURAZIONE ---
# Leggi i segreti dalle variabili d'ambiente di GitHub Actions
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GIST_ID = os.getenv('GIST_ID')
GIST_SECRET_TOKEN = os.getenv('GIST_SECRET_TOKEN')

# Nome del file all'interno del Gist
GIST_FILENAME = 'processed_ids_montecorvino.txt'

# --- URL STABILI ---
BASE_URL = "https://montecorvinopugliano.trasparenza-valutazione-merito.it/"
START_URL = "https://montecorvinopugliano.trasparenza-valutazione-merito.it/web/trasparenza/papca-ap/-/papca/igrid/1173286/25141"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}


def get_gist_content():
    """Recupera il contenuto del file dal Gist."""
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/gists/{GIST_ID}'
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        gist_data = response.json()
        if GIST_FILENAME in gist_data['files']:
            return gist_data['files'][GIST_FILENAME]['content']
        return ""
    except Exception as e:
        print(f"❌ Errore nel recuperare il Gist: {e}. Parto con una lista vuota.")
        return ""

def update_gist_content(new_content):
    """Aggiorna il contenuto del file nel Gist."""
    headers = {'Authorization': f'token {GIST_SECRET_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    url = f'https://api.github.com/gists/{GIST_ID}'
    payload = {'files': {GIST_FILENAME: {'content': new_content}}}
    try:
        response = requests.patch(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        print("✅ Gist aggiornato con successo.")
    except Exception as e:
        print(f"❌ Errore nell'aggiornare il Gist: {e}")

def send_telegram_notification(publication):
    """Invia una notifica tramite il bot di Telegram."""
    message_parts = [
        f"🔔 *Nuova Pubblicazione (Montecorvino P.)*",
        f"\n*Oggetto:* {publication['oggetto']}",
        f"\n*Tipo Atto:* {publication['tipo']}",
        f"*Numero:* {publication['numero']} del {publication['data_pubblicazione']}",
        f"\n[Vedi Dettagli e Allegati]({publication['url_dettaglio']})"
    ]
    final_message = "\n".join(message_parts)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': final_message, 'parse_mode': 'Markdown'}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        if response.json().get('ok'):
            print(f"✅ Notifica inviata per l'atto n. {publication['numero']}")
        else:
            print(f"❌ Errore API Telegram: {response.json().get('description')}")
    except Exception as e:
        print(f"❌ Eccezione durante l'invio della notifica: {e}")

def check_for_new_publications():
    """Funzione principale che controlla, confronta e notifica."""
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GIST_ID, GIST_SECRET_TOKEN]):
        print("❌ ERRORE: Una o più credenziali (Secrets) non sono state impostate.")
        return

    print("--- Avvio controllo nuove pubblicazioni (Montecorvino Pugliano) ---")
    gist_content = get_gist_content()
    processed_ids = set(gist_content.splitlines())
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
                numero_atto = cells[0].get_text(strip=True)
                tipo_atto = ' / '.join(cells[1].get_text(separator=' ').split())
                oggetto = cells[2].get_text(strip=True)
                data_inizio = cells[3].get_text(strip=True).split()[0]
                detail_link_tag = cells[4].find('a', title='Apri Dettaglio')
                url_dettaglio = urljoin(BASE_URL, detail_link_tag['href']) if detail_link_tag else ''

                publication_details = {
                    'id': act_id, 'oggetto': oggetto, 'numero': numero_atto,
                    'tipo': tipo_atto, 'data_pubblicazione': data_inizio,
                    'url_dettaglio': url_dettaglio
                }
                new_publications_to_notify.append(publication_details)

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
        
        new_ids_found = [p['id'] for p in new_publications_to_notify]
        final_content = gist_content + "\n" + "\n".join(new_ids_found)
        update_gist_content(final_content.strip())

    print("--- Controllo terminato ---")

if __name__ == "__main__":
    check_for_new_publications()
