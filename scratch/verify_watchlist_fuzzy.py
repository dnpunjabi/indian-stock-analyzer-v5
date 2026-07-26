import urllib.request, json

url = 'http://127.0.0.1:8000/api/watchlists'
try:
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read().decode())
    for w in data:
        print(f"=== Watchlist: {w['name']} ===")
        for item in w['items']:
            sym = item.get('symbol', '')
            score = item.get('fuzzy_score')
            rating = item.get('fuzzy_rating')
            print(f"  Symbol: {sym:<15} | Fuzzy Score: {score}% | Rating: {rating}")
except Exception as e:
    print(f"Error fetching watchlists: {e}")
