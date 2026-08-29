import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(override=True)

gemini_keys = [v for k, v in os.environ.items() if k.startswith("GEMINI_API_KEY") and v.strip()]
gemini_key = gemini_keys[0]

models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3.6-flash"]

for m in models:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={gemini_key}"
    payload = {"contents": [{"role": "user", "parts": [{"text": "Say Hello"}]}]}
    try:
        res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=10.0)
        if res.status_code == 200:
            txt = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            print(f"[SUCCESS] {m}: {txt.strip()}")
        else:
            print(f"[FAIL] {m}: {res.status_code} {res.text[:150]}")
    except Exception as e:
        print(f"[ERROR] {m}: {e}")
