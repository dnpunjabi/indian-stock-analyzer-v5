import sys
import io
import json
import asyncio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from backend.main import get_stage_diagnostic

async def run():
    print("=== STAGE DIAGNOSTIC FOR BHEL.NS ===")
    res_bhel = await get_stage_diagnostic('BHEL.NS', force_refresh=True)
    q_bhel = 0
    for k, v in res_bhel.get('screener_status', {}).items():
        if v.get('qualified'):
            q_bhel += 1
            print(f"  [QUALIFIED] {k}: {v.get('reason')}")
        else:
            print(f"  [REJECTED]  {k}: {v.get('reason')}")
    print(f"TOTAL QUALIFIED BHEL: {q_bhel}")

    print("\n=== STAGE DIAGNOSTIC FOR LALPATHLAB.NS ===")
    res_lal = await get_stage_diagnostic('LALPATHLAB.NS', force_refresh=True)
    q_lal = 0
    for k, v in res_lal.get('screener_status', {}).items():
        if v.get('qualified'):
            q_lal += 1
            print(f"  [QUALIFIED] {k}: {v.get('reason')}")
        else:
            print(f"  [REJECTED]  {k}: {v.get('reason')}")
    print(f"TOTAL QUALIFIED LALPATHLAB: {q_lal}")

if __name__ == '__main__':
    asyncio.run(run())
