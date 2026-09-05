import pytest
import sqlite3
import os
import sys

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.main import (
    init_db,
    get_db,
    check_quant_alert_history,
    record_quant_alert_history
)

def test_quant_whatsapp_history_table():
    """Verify that quant_whatsapp_alert_history table is initialized correctly."""
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quant_whatsapp_alert_history'")
        row = cursor.fetchone()
        assert row is not None, "quant_whatsapp_alert_history table should exist in SQLite database"

def test_quant_whatsapp_deduplication():
    """Verify that deduplication engine correctly flags duplicates and resets on state changes."""
    init_db()
    test_symbol = "TEST_QUANT_STOCK.NS"
    setup_type = "STAGE2_BREAKOUT"
    stage_1 = "STAGE 2: MARK-UP"
    stage_2 = "STAGE 4: MARK-DOWN"

    # Cleanup any pre-existing test row for idempotency
    with get_db() as conn:
        conn.cursor().execute("DELETE FROM quant_whatsapp_alert_history WHERE symbol = ?", (test_symbol,))
        conn.commit()

    # 1. Before recording, check should return False (Not alerted)
    is_alerted = check_quant_alert_history(test_symbol, setup_type, stage_1)
    assert is_alerted is False, "New stock should NOT be flagged as already alerted"

    # 2. Record alert in history
    record_quant_alert_history(test_symbol, setup_type, stage_1, "3/4 TRIPLE QUALIFIED")

    # 3. Immediately checking same stage should return True (Deduplicated / Skipped)
    is_alerted_again = check_quant_alert_history(test_symbol, setup_type, stage_1)
    assert is_alerted_again is True, "Repeat scan in same stage MUST be flagged as already alerted (Deduplicated)"

    # 4. Checking a different stage (stage shift) should return False (Reset for new alert)
    is_alerted_new_stage = check_quant_alert_history(test_symbol, setup_type, stage_2)
    assert is_alerted_new_stage is False, "State transition to a new stage should allow a new alert"

def test_test_quant_whatsapp_endpoint():
    """Test the developer test API endpoint using FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    response = client.post("/api/screener/test-quant-whatsapp?symbol=BOSCHLTD.NS")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["symbol"] == "BOSCHLTD.NS"
