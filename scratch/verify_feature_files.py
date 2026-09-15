with open("backend/static/app.js", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

assert "openConfluenceWatchlistModal" in content, "openConfluenceWatchlistModal missing!"
assert "submitConfluenceWatchlist" in content, "submitConfluenceWatchlist missing!"
assert "btn-confluence-create-watchlist" in content, "btn-confluence-create-watchlist missing!"

with open("backend/static/styles.css", "r", encoding="utf-8", errors="ignore") as f:
    css = f.read()

assert "confluence-modal-backdrop" in css, "confluence-modal-backdrop missing!"
assert "data-mode=\"light\"" in css, "light theme support missing!"

print("✅ Both app.js and styles.css verified successfully!")
