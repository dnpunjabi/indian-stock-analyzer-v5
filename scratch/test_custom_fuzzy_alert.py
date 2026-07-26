import urllib.request
import json

url = "http://127.0.0.1:8000/api/alerts/set"

payload = {
    "ticker": "BOSCHLTD.NS",
    "condition_type": "FUZZY_SCORE",
    "operator": ">=",
    "value": "70"
}

req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        print("Created Custom Fuzzy Alert via /api/alerts/set:", res)
except Exception as e:
    print("Error creating custom alert:", e)
