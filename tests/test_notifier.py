import os
import requests
from dotenv import load_dotenv

load_dotenv()

# Option A: If using ntfy.sh
topic = os.getenv("NTFY_TOPIC")
if topic:
    res = requests.post(f"https://ntfy.sh/{topic}", data="Test notification from CSMID!")
    print(f"Ntfy Status: {res.status_code}, Response: {res.text}")

# Option B: If using Pushover
user_key = os.getenv("PUSHOVER_USER_KEY")
api_token = os.getenv("PUSHOVER_TOKEN")
if user_key and api_token:
    res = requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": api_token,
            "user": user_key,
            "message": "Test notification from CSMID!"
        }
    )
    print(f"Pushover Status: {res.status_code}, Response: {res.text}")