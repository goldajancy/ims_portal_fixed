import os
from dotenv import load_dotenv
load_dotenv()

import requests

token    = os.getenv("WHATSAPP_TOKEN")
phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
version  = os.getenv("WHATSAPP_API_VERSION", "v21.0")

print("TOKEN loaded:", bool(token))
print("PHONE_ID loaded:", bool(phone_id))

YOUR_NUMBER = "919876543210"  # ← put your WhatsApp number here

url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
payload = {
    "messaging_product": "whatsapp",
    "to": YOUR_NUMBER,
    "type": "template",
    "template": {
        "name": "lms_welcome_student",
        "language": {"code": "en"},
        "components": [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Test Student"},
                {"type": "text", "text": "Test Class"}
            ]
        }]
    }
}
resp = requests.post(url, headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}, json=payload)

print("Status:", resp.status_code)
print("Response:", resp.json())