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

async def main():
    async with httpx.AsyncClient() as c:
        txn = f"D{int(time.time())}0001"   # 12-digit format (MALFORMED na aaye)
        print("AMOUNT TAMPER TEST")
        print(f"[1] Request bheji: {txn} amount=100")
        await send(c, evt("DEPOSIT_REQUESTED", txn, 100,
                          {"method": "bank", "agent_id": AGENT, "utr": f"UTR{int(time.time())}"}))
        await asyncio.sleep(1)

        print(f"[2] Approve bheji: SAME {txn} par amount=100000 (TAMPER!)")
        await send(c, evt("DEPOSIT_APPROVED", txn, 100000,
                          {"agent_id": AGENT, "bonus": 0, "user_closing": 100000, "agent_closing": 5000}))
        await asyncio.sleep(2)

        print("DONE — Telegram/journalctl dekho:")
        print("Expected: AMOUNT_CHANGED_AT_APPROVAL (request 100, approve 100000)")

asyncio.run(main())