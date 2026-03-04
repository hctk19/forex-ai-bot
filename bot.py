import requests
import time

BOT_TOKEN = "8120696414:AAECnMRaLkst_y7uX3dDGeQ6QeCr350R0ac"
CHAT_ID = "1532734735"

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }
    requests.post(url, json=payload)

send_message("Forex analiz botu aktif 🚀")

while True:
    time.sleep(3600)
