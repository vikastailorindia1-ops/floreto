import asyncio
import time
import httpx

COLLECTOR = "http://localhost:8001/events"

def evt(t, txn, amount=None, meta=None):
    return {"event_id": f"test-{int(time.time()*1000)}-{txn}", "timestamp": "2026-09-07T00:00:00Z",
            "service": "game", "event_type": t, "transaction_id": txn, "amount": amount, "metadata": meta or {}}

async def send(c, e):
    r = await c.post(COLLECTOR, json=e, timeout=5)
    return r.status_code

USER = "6a63136f72dbb3f11b4bef8f"
AGENT = "6a66072fec5867e3e3f3d94d"

STEPS = ["GUARDS_PASSED", "BONUS_CHECKED", "BALANCE_OK", "AGENT_DEBITED",
         "USER_CREDITED", "STATEMENTS_WRITTEN", "SUCCESS_RECORDED"]

async def flow(c, txn, skip=None):
    skip = skip or []
    for s in STEPS:
        if s in skip:
            continue
        await send(c, evt("TXN_STEP", txn, meta={"flow": "DEPOSIT_APPROVE", "step": s, "user_id": USER}))
        await asyncio.sleep(0.1)
    await send(c, evt("DEPOSIT_APPROVED", txn, 500,
                      {"agent_id": AGENT, "bonus": 0, "user_closing": 5000, "agent_closing": 10000}))

async def main():
    async with httpx.AsyncClient() as c:
        print("DEPOSIT-APPROVE NIGARANI TEST")
        print("[1] Poora sahi flow (koi alert nahi)...")
        await flow(c, f"D{int(time.time())}01")
        print("    bheja - koi alert nahi = PASS")
        await asyncio.sleep(2)
        for s in STEPS:
            print(f"[2] {s} SKIP...")
            await flow(c, f"D{int(time.time())}{s[:3]}", skip=[s])
            print(f"    bheja - {s} missing = PASS")
            await asyncio.sleep(2)
        print("DONE - journalctl dekho")

asyncio.run(main())