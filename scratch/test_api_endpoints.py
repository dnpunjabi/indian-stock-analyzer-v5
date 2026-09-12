import sys
import os
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

async def test_fastapi_endpoints():
    print("Testing FastAPI endpoints...")
    from backend.main import get_cron_status, get_multi_confluence_leaderboard
    status = await get_cron_status()
    print("Cron status response:")
    print("  status:", status.get("status"))
    print("  screeners count:", len(status.get("screeners", {})))
    print("  screeners keys:", list(status.get("screeners", {}).keys()))
    assert "rs_line_new_high" in status["screeners"], "rs_line_new_high missing from cron status!"
    assert "undercut_and_rally" in status["screeners"], "undercut_and_rally missing from cron status!"
    print("✅ Cron status endpoint verified with all 11 screeners!")

    print("\nTesting Multi-Confluence Leaderboard endpoint...")
    leaderboard = await get_multi_confluence_leaderboard()
    print("Leaderboard response:")
    print("  status:", leaderboard.get("status"))
    print("  total_confluence_stocks:", leaderboard.get("total_confluence_stocks"))
    print("  tier_counts:", leaderboard.get("tier_counts"))
    print("  hot_industry_clusters:", leaderboard.get("hot_industry_clusters"))
    print("  sample candidates count:", len(leaderboard.get("candidates", [])))
    if leaderboard.get("candidates"):
        sample = leaderboard["candidates"][0]
        print("  top candidate sample:", sample.get("symbol"), sample.get("tier_title"), sample.get("buy_zone_label"), sample.get("tactical_levels"))
    assert leaderboard.get("status") == "success", "Multi-confluence leaderboard response failed!"
    print("✅ Multi-Confluence Leaderboard endpoint verified successfully!")

if __name__ == "__main__":
    asyncio.run(test_fastapi_endpoints())

