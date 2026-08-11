import pytest
import asyncio
import time
from backend.websocket_server import ConnectionManager, TickStore, _broadcast_loop

@pytest.mark.anyio
async def test_connection_manager_concurrency():
    """Verify ConnectionManager handles rapid concurrent connections/subscriptions without RuntimeError."""
    manager = ConnectionManager()
    
    class FakeWebSocket:
        def __init__(self, client_id):
            self.id = client_id
            self.sent = []
        async def accept(self):
            pass
        async def send_json(self, data):
            self.sent.append(data)

    fake_sockets = [FakeWebSocket(i) for i in range(50)]

    async def simulate_client(ws, idx):
        await manager.connect(ws)
        symbols = [f"STOCK_{idx % 10}", "RELIANCE", "TCS"]
        await manager.subscribe(ws, symbols)
        all_syms = manager.get_all_subscribed_symbols()
        assert isinstance(all_syms, set)
        await manager.unsubscribe(ws, ["TCS"])
        if idx % 2 == 0:
            await manager.disconnect(ws)

    # Launch 50 concurrent tasks
    tasks = [simulate_client(ws, i) for i, ws in enumerate(fake_sockets)]
    await asyncio.gather(*tasks)

    # Test broadcast_ticks under concurrent mutation
    ticks = {
        "RELIANCE": {"price": 2500.0, "change": 10.0, "change_pct": 0.4},
        "TCS": {"price": 3400.0, "change": -5.0, "change_pct": -0.15}
    }
    
    # Broadcast ticks to all active connections
    await manager.broadcast_ticks(ticks, source="test")
    assert manager.client_count == 25

def test_tick_store():
    """Verify TickStore thread-safety and updates."""
    store = TickStore()
    store.update("INFY", {"price": 1400.0, "change": 5.0})
    store.update("TCS", {"price": 3200.0, "change": 12.0})

    assert store.get("INFY")["price"] == 1400.0
    assert store.count == 2
    batch = store.get_batch(["INFY", "NONEXISTENT"])
    assert "INFY" in batch
    assert "NONEXISTENT" not in batch

def test_fastapi_ping_pong():
    """Test FastAPI TestClient ping/pong WebSocket frame handling."""
    from fastapi.testclient import TestClient
    from backend.websocket_server import angel_ws_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(angel_ws_router)
    client = TestClient(app)

    with client.websocket_connect("/ws/live-ticks") as websocket:
        # Send Ping frame
        websocket.send_json({"action": "ping"})
        data = websocket.receive_json()
        assert data["type"] == "pong"
        assert "timestamp" in data

        # Send Subscribe frame
        websocket.send_json({"action": "subscribe", "symbols": ["TCS"]})
