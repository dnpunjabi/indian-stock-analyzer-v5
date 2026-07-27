import pytest
from backend.fuzzy_engine import triangle, trapezoid, evaluate_fuzzy_logic

def test_membership_functions():
    # Test triangle
    assert triangle(5.0, 0.0, 5.0, 10.0) == 1.0
    assert triangle(0.0, 0.0, 5.0, 10.0) == 0.0
    assert triangle(10.0, 0.0, 5.0, 10.0) == 0.0
    assert triangle(2.5, 0.0, 5.0, 10.0) == 0.5

    # Test trapezoid
    assert trapezoid(5.0, 2.0, 4.0, 6.0, 8.0) == 1.0
    assert trapezoid(1.0, 2.0, 4.0, 6.0, 8.0) == 0.0
    assert trapezoid(3.0, 2.0, 4.0, 6.0, 8.0) == 0.5
    assert trapezoid(7.0, 2.0, 4.0, 6.0, 8.0) == 0.5

def test_rule_101_and_104_stage2_breakout_and_dma_stack():
    res = evaluate_fuzzy_logic(
        opm_delta=1.0, roe_delta=1.0, debt_delta=0.0,
        rsi=55.0, dma_prox=4.0, adx=32.0, stage=2,
        altman_z=4.0, piotroski=7, promoter_holding=55.0, promoter_pledge_delta=0.0,
        relative_volume=1.5, sector_markdown=False,
        dma_stack_bullish=True, fifty_two_week_prox=0.92
    )
    assert res["fuzzy_score"] >= 40.0
    assert res["rating"] in ["Buy", "Strong Buy"]
    rule_ids = [r["rule_id"] for r in res["rule_trail"]]
    assert 101 in rule_ids # Stage-2 Breakout
    assert 104 in rule_ids # Bullish DMA Stack
    assert 105 in rule_ids # 52W High Breakout

def test_rule_103_valuation_bargain():
    res = evaluate_fuzzy_logic(
        opm_delta=1.5, roe_delta=2.0, debt_delta=-0.5,
        rsi=42.0, dma_prox=0.5, adx=22.0, stage=1,
        altman_z=3.5, piotroski=8, promoter_holding=60.0, promoter_pledge_delta=0.0,
        relative_volume=1.1, sector_markdown=False,
        pe_valuation_ratio=0.75 # Current P/E is 25% below 3Y Median PE
    )
    rule_ids = [r["rule_id"] for r in res["rule_trail"]]
    assert 103 in rule_ids # Valuation Bargain Alignment

def test_rule_106_stealth_delivery_and_108_vcp_squeeze():
    res = evaluate_fuzzy_logic(
        opm_delta=1.0, roe_delta=1.0, debt_delta=0.0,
        rsi=45.0, dma_prox=0.0, adx=16.0, stage=1,
        altman_z=3.2, piotroski=6, promoter_holding=50.0, promoter_pledge_delta=0.0,
        relative_volume=0.5, sector_markdown=False,
        delivery_pct=72.0, # High stealth delivery %
        vcp_squeeze=True   # Volatility squeeze
    )
    rule_ids = [r["rule_id"] for r in res["rule_trail"]]
    assert 106 in rule_ids # Stealth Delivery Spike
    assert 108 in rule_ids # VCP Squeeze

def test_rule_107_fii_dii_institutional_flow():
    res = evaluate_fuzzy_logic(
        opm_delta=1.0, roe_delta=1.0, debt_delta=0.0,
        rsi=50.0, dma_prox=1.0, adx=20.0, stage=2,
        altman_z=4.0, piotroski=7, promoter_holding=55.0, promoter_pledge_delta=0.0,
        relative_volume=1.2, sector_markdown=False,
        fii_dii_delta=1.2 # Strong institutional net buying
    )
    rule_ids = [r["rule_id"] for r in res["rule_trail"]]
    assert 107 in rule_ids # FII/DII Institutional Accumulation

def test_rule_303_overvaluation_bubble_and_304_bearish_stack():
    res = evaluate_fuzzy_logic(
        opm_delta=-3.0, roe_delta=-2.0, debt_delta=1.0,
        rsi=60.0, dma_prox=-6.0, adx=30.0, stage=4,
        altman_z=2.5, piotroski=5, promoter_holding=40.0, promoter_pledge_delta=0.0,
        relative_volume=0.9, sector_markdown=True,
        pe_valuation_ratio=1.65, # Overvalued by 65% over median
        dma_stack_bearish=True   # Bearish DMA stack
    )
    assert res["fuzzy_score"] <= -15.0
    assert res["rating"] in ["Sell", "Strong Sell"]
    rule_ids = [r["rule_id"] for r in res["rule_trail"]]
    assert 303 in rule_ids # Overvaluation Bubble Warning
    assert 304 in rule_ids # Bearish DMA Stack Breakdown

def test_rule_405_cash_flow_and_solvency_safeguard():
    res = evaluate_fuzzy_logic(
        opm_delta=3.0, roe_delta=3.0, debt_delta=0.0,
        rsi=55.0, dma_prox=2.0, adx=25.0, stage=2,
        altman_z=3.5, piotroski=7, promoter_holding=60.0, promoter_pledge_delta=0.0,
        relative_volume=1.2, sector_markdown=False,
        icr=1.0,           # Distressed Interest Coverage Ratio (< 1.5)
        ocf_pat_ratio=0.35 # Accrual trap (Cash flow < 50% of Net Profit)
    )
    assert res["fuzzy_score"] <= 18.0 # Capped score due to Rule 405
    rule_ids = [r["rule_id"] for r in res["rule_trail"]]
    assert 405 in rule_ids # Solvency & Cash Flow Trap Cap

def test_api_fuzzy_endpoints():
    import json
    from fastapi.testclient import TestClient
    from backend.main import app, get_db
    client = TestClient(app)

    # Insert test profile into db so evaluate endpoint finds it
    with get_db() as conn:
        mock_profile = {
            "symbol": "CONSTRUCTIONMATERIALS.NS",
            "fundamentals": {"opm_growth_3y": 1.0, "roe_growth_3y": 1.0, "debt_to_equity": 0.5, "altman_z_score": 4.0, "piotroski_f_score": 7, "promoter_holding": 55.0},
            "technicals": {"rsi": 55.0, "dma_prox_pct": 4.0, "adx": 32.0, "stage": 2, "relative_volume": 1.5, "dma_stack_bullish": True, "fifty_two_week_prox": 0.92},
            "earnings_quality": {}
        }
        conn.execute("INSERT OR REPLACE INTO cached_profiles (symbol, profile_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", ("CONSTRUCTIONMATERIALS.NS", json.dumps(mock_profile)))
        conn.commit()

    # Test universe standings
    response = client.get("/api/fuzzy/universe-standings?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert "top_buys" in data
    assert "top_sells" in data
    
    # Test single stock evaluate endpoint
    response = client.get("/api/fuzzy/evaluate?symbol=CONSTRUCTIONMATERIALS.NS")
    assert response.status_code == 200
    eval_data = response.json()
    assert "fuzzy_score" in eval_data
    assert "rating" in eval_data
    assert "inputs" in eval_data
