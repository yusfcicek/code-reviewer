"""A client that carries its own credentials."""

import requests

API_KEY = "sk_live_9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"
DATABASE_PASSWORD = "Pr0duct10n!Passw0rd"


def fetch_account(account_id):
    response = requests.get(
        f"https://api.example.com/accounts/{account_id}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=10,
    )
    return response.json()
