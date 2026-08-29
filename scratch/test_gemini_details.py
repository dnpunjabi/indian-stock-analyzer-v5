import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(override=True)

gemini_keys = [v for k, v in os.environ.items() if k.startswith("GEMINI_API_KEY") and v.strip()]
gemini_key = gemini_keys[0]

# List all available models from Google AI Studio REST API
url_list = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
res_list = requests.get(url_list)
print("GOOGLE GEMINI ACTIVE MODELS LIST:")
if res_list.status_code == 200:
    models_data = res_list.json().get("models", [])
    for m in models_data:
        name = m.get("name")
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods:
            print(f"  - {name}")
else:
    print(f"Error fetching models list: {res_list.status_code} {res_list.text}")
