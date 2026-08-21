# ai/investigator.py — 🕵️ Qwen detective: INC code do, jaanch-report lo
import asyncio
import json
import os
import sys

import asyncpg
import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pymongo import AsyncMongoClient
from bson import ObjectId

load_dotenv()
PG_DSN = "postgresql://floreto:floreto_dev_pass@localhost:5432/security"
qwen = AsyncOpenAI(base_url="http://localhost:8000/v1", api_key="none")

GAME_URI = os.getenv("GAME_MONGO_URI", "")
GAME_DB = os.getenv("GAME_MONGO_DB", "")
game = AsyncMongoClient(GAME_URI)[GAME_DB] if GAME_URI and GAME_DB else None

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

SYSTEM = """Tum ek betting-platform ke senior fraud investigator ho.
Tumhe ek security incident + uska evidence milega. Sirf diye gaye FACTS use karo — kuch bhi assume/invent mat karo.
Report EXACTLY is format me, Hinglish me, chhoti aur seedhi:
KYA HUA: <1-2 line>
ROOT CAUSE (shak): <sabse likely wajah; agar evidence kam hai to saaf likho 'evidence adhoora'>
FINANCIAL IMPACT: <₹ amount ya 'zero/unknown'>
EVIDENCE: <2-3 bullet, sirf diye gaye data se>
CONFIDENCE: <0-100%>
RECOMMENDED ACTION: <1 line — monitor / txn freeze / manual review>"""


async def gather_case(inc_code: str) -> dict | None:
    pg = await asyncpg.connect(PG_DSN)
    try:
        row = await pg.fetchrow("SELECT * FROM incidents WHERE incident_code=$1", inc_code)
        if not row:
            return None
        case = {"incident": dict(row), "event": json.loads(row["event"]),
                "related": [dict(r) for r in await pg.fetch(
                    "SELECT incident_code, rule, severity, message, created_at FROM incidents WHERE event->>'transaction_id' = $1 AND incident_code != $2 ORDER BY id",
                    json.loads(row["event"]).get("transaction_id") or "", inc_code)]}
    finally:
        await pg.close()
    # Atlas se user ka sach (read-only)
    case["db_facts"] = {}
    ev = case["event"]
    if game is not None and ev.get("user_id"):
        try:
            uid = ObjectId(str(ev["user_id"]))
            u = await game.users.find_one({"_id": uid}, {"clientname": 1, "AccountTypecheck": 1, "parentId": 1})
            m = await game.usermetas.find_one({"userId": uid}, {"availableBalance": 1, "exposure": 1})
            if u:
                case["db_facts"]["user"] = {"clientname": u.get("clientname"), "type": u.get("AccountTypecheck")}
            if m:
                case["db_facts"]["asli_balance"] = m.get("availableBalance")
        except Exception as e:
            case["db_facts"]["error"] = str(e)
    return case


async def investigate(inc_code: str) -> str:
    case = await gather_case(inc_code)
    if not case:
        return f"❌ {inc_code} diary me nahi mila."
    inc = case["incident"]
    prompt = (f"INCIDENT: {inc['incident_code']} | rule={inc['rule']} | severity={inc['severity']}\n"
              f"MESSAGE: {inc['message']}\n"
              f"EVENT: {json.dumps(case['event'], default=str)}\n"
              f"DB FACTS (Atlas, abhi ka sach): {json.dumps(case['db_facts'], default=str)}\n"
              f"SAME TXN KE DOOSRE INCIDENTS: {json.dumps(case['related'], default=str)}")
    resp = await qwen.chat.completions.create(
        model="qwen3.6-27b",
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=6000, temperature=0.2,
    )
    msg = resp.choices[0].message
    report = (msg.content or "").strip()
    if not report:  # reasoning-model trap: poora budget soch me gaya
        thinking = (getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or "").strip()
        fr = resp.choices[0].finish_reason
        report = (f"⚠️ Final jawab nahi bana (finish_reason={fr}).\n"
                  + (f"Detective ki adhoori soch (aakhri hissa):\n...{thinking[-1200:]}" if thinking else "max_tokens aur badhao."))
    if resp.usage:
        print(f"   (tokens: prompt={resp.usage.prompt_tokens}, soch+jawab={resp.usage.completion_tokens})")
    return f"🕵️ JAANCH REPORT — {inc_code} [{inc['severity']}] {inc['rule']}\n\n{report}"


async def send_telegram(text: str):
    if not BOT or not CHAT:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"https://api.telegram.org/bot{BOT}/sendMessage",
                     json={"chat_id": CHAT, "text": text[:4000]})


async def main():
    inc = sys.argv[1] if len(sys.argv) > 1 else ""
    if not inc:
        print("Usage: python3 -m ai.investigator INC-XXXXXXXX")
        return
    print("🕵️ jaanch shuru...")
    report = await investigate(inc)
    print("\n" + report)
    await send_telegram(report)
    print("\n📱 Telegram pe bhi bheji.")


if __name__ == "__main__":
    asyncio.run(main())