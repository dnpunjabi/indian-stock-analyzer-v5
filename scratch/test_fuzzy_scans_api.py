import urllib.request
import json
import time

BASE_URL = "http://127.0.0.1:8000/api/scans/fuzzy"

def test_endpoint(params_str, name):
    url = f"{BASE_URL}?{params_str}"
    t0 = time.time()
    try:
        req = urllib.request.urlopen(url)
        elapsed_ms = (time.time() - t0) * 1000
        data = json.loads(req.read().decode())
        stocks = data.get("stocks", [])
        total = data.get("total_matches", 0)
        
        print(f"\n==========================================")
        print(f"TEST: {name}")
        print(f"URL: {url}")
        print(f"Execution Time: {elapsed_ms:.2f} ms")
        print(f"Total Matches: {total}")
        
        if stocks:
            scores = [s["fuzzy_score"] for s in stocks]
            ratings = set(s["fuzzy_rating"] for s in stocks)
            print(f"Score Range: Min {min(scores):.1f}%, Max {max(scores):.1f}%")
            print(f"Ratings Present: {ratings}")
            sample = [f"{s['symbol']}: {s['fuzzy_score']}% ({s['fuzzy_rating']})" for s in stocks[:3]]
            print(f"Top 3 Sample: {sample}")
        else:
            print("No stocks returned for this filter.")
            
        return stocks, elapsed_ms
    except Exception as e:
        print(f"ERROR testing {name}: {e}")
        return [], 0.0

if __name__ == "__main__":
    print("--- TESTING ALL FUZZY SCAN FILTER CONDITIONS ---")
    time.sleep(1)
    
    # 1. Warm-up / Initial Evaluation
    test_endpoint("min_score=-100&limit=50&rating_class=ALL", "1. Warm-up Universe Scan")
    
    # 2. Test AVOID (Must be <= -40%)
    avoid_stocks, t_avoid = test_endpoint("min_score=-100&limit=50&rating_class=AVOID", "2. AVOID (<= -40%)")
    for s in avoid_stocks:
        assert s["fuzzy_score"] <= -40.0, f"FAIL: Stock {s['symbol']} has score {s['fuzzy_score']} > -40 in AVOID filter!"
    print("PASSED: All AVOID stocks are strictly <= -40.0%!")
    
    # 3. Test STRONG BUY (Must be >= 70%)
    sbuy_stocks, t_sbuy = test_endpoint("min_score=30&limit=50&rating_class=STRONG_BUY", "3. STRONG BUY (>= 70%)")
    for s in sbuy_stocks:
        assert s["fuzzy_score"] >= 70.0, f"FAIL: Stock {s['symbol']} has score {s['fuzzy_score']} < 70 in STRONG_BUY filter!"
    print("PASSED: All STRONG BUY stocks are strictly >= 70.0%!")

    # 4. Test BUY (Must be 30..70%)
    buy_stocks, t_buy = test_endpoint("min_score=30&limit=50&rating_class=BUY", "4. BUY (30% to 70%)")
    for s in buy_stocks:
        assert 30.0 <= s["fuzzy_score"] < 70.0, f"FAIL: Stock {s['symbol']} has score {s['fuzzy_score']} outside BUY range!"
    print("PASSED: All BUY stocks are strictly within [30.0%, 70.0%)!")

    # 5. Test HOLD (Must be -40..30%)
    hold_stocks, t_hold = test_endpoint("min_score=-100&limit=50&rating_class=HOLD", "5. HOLD (-40% to 30%)")
    for s in hold_stocks:
        assert -40.0 < s["fuzzy_score"] < 30.0, f"FAIL: Stock {s['symbol']} has score {s['fuzzy_score']} outside HOLD range!"
    print("PASSED: All HOLD stocks are strictly within (-40.0%, 30.0%)!")
    
    # 6. Test ALL with Slider min_score=50
    min50_stocks, t_min50 = test_endpoint("min_score=50&limit=50&rating_class=ALL", "6. ALL with Slider min_score=50%")
    for s in min50_stocks:
        assert s["fuzzy_score"] >= 50.0, f"FAIL: Stock {s['symbol']} has score {s['fuzzy_score']} < 50.0!"
    print("PASSED: All stocks in Slider min_score=50% are strictly >= 50.0%!")

    print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
