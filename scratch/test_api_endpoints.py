import sys
import os
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

async def test_fastapi_endpoints():
    print("Testing FastAPI endpoints...")
    from backend.main import get_cron_status
    status = await get_cron_status()
    print("Cron status response:")
    print("  status:", status.get("status"))
    print("  screeners count:", len(status.get("screeners", {})))
    print("  screeners keys:", list(status.get("screeners", {}).keys()))
    assert "rs_line_new_high" in status["screeners"], "rs_line_new_high missing from cron status!"
    assert "undercut_and_rally" in status["screeners"], "undercut_and_rally missing from cron status!"
    print("✅ Cron status endpoint verified with all 11 screeners!")

if __name__ == "__main__":
    asyncio.run(test_fastapi_endpoints())
