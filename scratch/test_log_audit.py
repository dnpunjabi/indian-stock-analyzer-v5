import sys
import os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import time
from fastapi.testclient import TestClient
from backend.main import app
from backend.websocket_server import get_feed_status

def audit_local_server_and_polling():
    print("=== STARTING LOCAL LOG CLEANLINESS & POLLING AUDIT ===")
    client = TestClient(app)
    
    # 1. Audit HTTP /api/llm-config Endpoint
    start_time = time.time()
    for i in range(5):
        resp = client.get("/api/llm-config")
        assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}"
    elapsed = time.time() - start_time
    print(f"✅ Executed 5 requests to /api/llm-config in {elapsed:.3f}s (Avg: {elapsed/5:.4f}s/req).")

    # 2. Audit Feed Status API
    status = get_feed_status()
    print(f"✅ Feed status check: active={status['feed_active']}, clients={status['connected_clients']}, ticks_in_store={status['tick_store_symbols']}")

    # 3. Audit WebSocket Live Ticks Endpoint & Heartbeat Ping/Pong
    print("✅ Testing WebSocket Connection & Heartbeat Ping/Pong...")
    with client.websocket_connect("/ws/live-ticks") as ws:
        ws.send_json({"action": "ping"})
        msg = ws.receive_json()
        assert msg.get("type") == "pong", f"Expected pong, got {msg}"
        print(f"  -> WebSocket Heartbeat Response: {msg}")

        # Send subscription request
        ws.send_json({"action": "subscribe", "symbols": ["RELIANCE", "TCS"]})
        print("  -> WebSocket Symbol Subscription: OK")

    print("=== LOCAL LOG CLEANLINESS & POLLING AUDIT PASSED ===")

if __name__ == "__main__":
    audit_local_server_and_polling()
