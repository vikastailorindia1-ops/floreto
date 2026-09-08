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

SYSTEM = """Tum ek security guard ho jo game-admin ko SAADI bhasha me poori kahani batata hai.
Sirf diye gaye FACTS use karo — kuch invent mat karo.

Tumhe milega: incident ka rule, event ka data, aur SAME TXN ke doosre incidents (jo poori kahani banate hain).
DOOSRE INCIDENTS ko zaroor padho — usse pata chalta hai user ne kya-kya kiya step by step.

Report EXACTLY is format me, Hinglish me:

🔴 Kya hua: <1-2 line simple bhasha me — kya galat hua>

⚠️ User ne kya kiya: <2-3 line — user ne EXACTLY kya kiya, step by step.
   Jaise: "user2 ne pehle ek UTR se ₹500 ka deposit karvaya (approve ho gaya).
   Phir USI UTR se dobara ₹500 ki nayi request bheji — jo nahi honi chahiye thi.">

🐛 Bug/gadbad kaise hui: <2-3 line — technical wajah SIMPLE bhasha me.
   Jaise: "Normal flow me UTR-check hota hai jo duplicate rokta hai. Par is baar
   wo check chala hi nahi (bypass hua) — ya to code me bug hai ya kisi ne API se
   seedha request bheji guard ko skip karke. Isliye duplicate request ban gayi.">

👤 Kaun: <username>
💰 Paisa: <₹ amount>
🧾 Transaction: <txn id>
✅ Karo: <1-2 line — admin kya kare + developer kaunsi cheez check kare>

Simple bhasha, par POORI kahani. Developer ko samajh aaye ki kya, kaise, aur kahan dekhna hai."""


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
    # rule-name ki jagah aasaan heading (aam banda samjhe)
    icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}.get(inc["severity"], "⚪")

    # 🔧 Developer footer — kaunsa flow/step/rule, taaki dev turant sahi jagah dekhe
    ev = case["event"]
    meta = ev.get("event_type", "?")
    flow = (ev.get("metadata") or {}).get("flow", "")
    # rule se batao kaunsi file/function dekhni hai
    RULE_LOCATION = {
        "STEPS_MISSING_AT_FINAL":   "flow_rules.py → rule_flow_steps (koi emitStep miss hua)",
        "STEP_OUT_OF_ORDER":        "flow_rules.py → rule_flow_steps (step galat order)",
        "STEP_REPEATED":            "flow_rules.py → rule_flow_steps (step 2 baar)",
        "UTR_REUSED_AT_REQUEST":    "db_rules.py → rule_db_utr_reused_at_request (submitDepositRequest ka UTR guard)",
        "DUPLICATE_UTR":            "db_rules.py → rule_db_duplicate_utr (depositsuccess ka UTR check)",
        "UTR_STOLEN":               "db_rules.py → rule_db_utr_belongs_elsewhere",
        "DOUBLE_APPROVAL":          "real_rules.py → rule_double_approval (depositsuccess/withdrawsuccess)",
        "APPROVAL_WITHOUT_REQUEST": "real_rules.py → rule_ghost_or_tampered_approval",
        "BONUS_ABOVE_HARD_CAP":     "real_rules.py → rule_bonus_policy (depositsuccess bonus)",
        "USER_NOT_IN_DB":           "db_rules.py → rule_db_user_real (forged event)",
        "AGENT_NOT_IN_DB":          "db_rules.py → rule_db_user_real",
        "WRONG_AGENT_FOR_USER":     "db_rules.py → rule_db_user_real (hierarchy)",
        "MALFORMED_TXN_ID":         "real_rules.py → rule_flow_whitelist (event shape)",
        "MALFORMED_USER_ID":        "real_rules.py → rule_flow_whitelist",
        "MALFORMED_AGENT_ID":       "real_rules.py → rule_flow_whitelist",
        "NEGATIVE_CLOSING":         "real_rules.py → rule_closing_not_negative",
        "BAD_AMOUNT":               "real_rules.py → rule_amount_sane",
    }
    where = RULE_LOCATION.get(inc["rule"], "engine rules — manual check")

    # kaunsa game-function (event_type + flow se)
    GAME_FN = {
        "DEPOSIT_REQUESTED":  "submitDepositRequest (userDWCtrl.js)",
        "DEPOSIT_APPROVED":   "depositsuccess (admin controller)",
        "WITHDRAW_REQUESTED": "submitWithdrawRequest (userDWCtrl.js)",
        "WITHDRAWAL_PAID":    "withdrawsuccess (admin controller)",
        "TXN_STEP":           f"{flow} flow ka koi step" if flow else "step event",
    }
    game_fn = GAME_FN.get(meta, meta)

    # incident ka time — IST me (kab bug aaya)
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    ts = inc.get("created_at")
    if ts:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        time_str = ts.astimezone(IST).strftime("%d-%b-%Y %I:%M:%S %p IST")
    else:
        time_str = "?"

    dev_footer = (
        f"\n\n━━━ 🔧 DEVELOPER INFO ━━━\n"
        f"⏰ Kab hua: {time_str}\n"
        f"Rule: {inc['rule']}\n"
        f"Event: {meta}\n"
        f"Game function: {game_fn}\n"
        f"Engine location: {where}\n"
        f"Full message: {inc['message']}"
    )

    return f"{icon} SECURITY ALERT\n(ref: {inc_code})\n\n{report}{dev_footer}"


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