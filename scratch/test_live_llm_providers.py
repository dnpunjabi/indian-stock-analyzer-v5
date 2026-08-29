import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(override=True)

print("="*60)
print("TESTING GEMINI MODELS LOCALLY")
print("="*60)

# 1. Get Gemini Keys
gemini_keys = [v for k, v in os.environ.items() if k.startswith("GEMINI_API_KEY") and v.strip()]
if not gemini_keys:
    print("NO GEMINI KEYS FOUND IN .ENV!")
else:
    gemini_key = gemini_keys[0]
    gemini_models_to_test = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-flash-latest"
    ]
    
    for m in gemini_models_to_test:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={gemini_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "Reply with 'SUCCESS' if you can read this."}]}]
        }
        try:
            res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=10.0)
            if res.status_code == 200:
                print(f"[GEMINI SUCCESS] Model '{m}' returned HTTP 200 OK")
            else:
                print(f"[GEMINI FAIL] Model '{m}' returned HTTP {res.status_code}: {res.text[:150]}")
        except Exception as e:
            print(f"[GEMINI ERROR] Model '{m}': {e}")

print("\n" + "="*60)
print("TESTING GROQ MODELS LOCALLY")
print("="*60)

groq_key = os.environ.get("GROQ_API_KEY", "") or os.environ.get("LLM_API_KEY", "")
if not groq_key:
    print("NO GROQ API KEY FOUND IN .ENV!")
else:
    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        
        # Query list of models from Groq API directly!
        try:
            models_list = client.models.list()
            print("ACTIVE GROQ MODELS RETURNED BY GROQ API:")
            active_ids = [m.id for m in models_list.data]
            for aid in active_ids:
                print(f"  - {aid}")
        except Exception as ex:
            print(f"Failed to fetch model list from Groq API: {ex}")
            active_ids = [
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "llama3-70b-8192",
                "mixtral-8x7b-32768",
                "gemma2-9b-it"
            ]

        print("\nTESTING SPECIFIC GROQ MODEL COMPLETIONS:")
        for gm in active_ids:
            try:
                comp = client.chat.completions.create(
                    messages=[{"role": "user", "content": "Reply SUCCESS"}],
                    model=gm,
                    max_tokens=10
                )
                print(f"[GROQ SUCCESS] Model '{gm}' returned: {comp.choices[0].message.content.strip()}")
            except Exception as e:
                print(f"[GROQ FAIL] Model '{gm}': {e}")
    except Exception as e:
        print(f"Groq test initialization error: {e}")
