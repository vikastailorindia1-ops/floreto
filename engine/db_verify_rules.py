# engine/db_rules.py — DB-VERIFIED checks: event ka jhooth vs Atlas ka sach
import os

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import AsyncMongoClient

load_dotenv()
GAME_URI = os.getenv("GAME_MONGO_URI", "")
GAME_DB = os.getenv("GAME_MONGO_DB", "")

_client = AsyncMongoClient(GAME_URI, serverSelectionTimeoutMS=5000) if GAME_URI else None
db = _client[GAME_DB] if (_client is not None and GAME_DB) else None

MONEY_EVENTS = {"DEPOSIT_APPROVED", "WITHDRAWAL_PAID"}
ALL_FLOW = MONEY_EVENTS | {"DEPOSIT_REQUESTED", "WITHDRAW_REQUESTED"}
EPS = 0.01


def _oid(s):
    try:
        return ObjectId(str(s))
    except Exception:
        return None


async def rule_db_user_real(event: dict) -> dict | None:
    """User/Agent Atlas me asli hain? Nakli id = forged event = CRITICAL."""
    if db is None or event.get("event_type") not in ALL_FLOW:
        return None
    try:
        et, txn = event["event_type"], event.get("transaction_id")
        uid = _oid(event.get("user_id"))
        if uid is None:
            return None  # format-jurm whitelist pehle hi pakad chuka
        u = await db.users.find_one({"_id": uid}, {"clientname": 1, "parentId": 1})
        if not u:
            return {"rule": "USER_NOT_IN_DB", "severity": "CRITICAL",
                    "message": f"{et} txn={txn}: user_id {event.get('user_id')} game DB me EXIST hi nahi karta — forged/fake event!"}
        meta = event.get("metadata") or {}
        aid = _oid(meta.get("agent_id"))
        if aid is not None:
            a = await db.users.find_one({"_id": aid}, {"clientname": 1})
            if not a:
                return {"rule": "AGENT_NOT_IN_DB", "severity": "CRITICAL",
                        "message": f"{et} txn={txn}: agent_id {meta.get('agent_id')} DB me nahi — forged event! (user '{u.get('clientname')}')"}
            if et in MONEY_EVENTS and u.get("parentId") is not None and str(u["parentId"]) != str(aid):
                rp = await db.users.find_one({"_id": u["parentId"]}, {"clientname": 1})
                return {"rule": "WRONG_AGENT_FOR_USER", "severity": "HIGH",
                        "message": f"{et} txn={txn}: user '{u.get('clientname')}' ka ASLI agent '{(rp or {}).get('clientname', '?')}' hai, lekin event me agent '{a.get('clientname')}' — hierarchy ke bahar approval!"}
        return None
    except Exception as e:
        print(f"⚠️ db rule skip (Atlas reachable nahi?): {e}")
        return None  # Atlas blip ho to bhi engine kabhi na mare


async def rule_db_closing_matches(event: dict) -> dict | None:
    """Event ne jo closing bola vs Atlas ka ASLI availableBalance."""
    if db is None or event.get("event_type") not in MONEY_EVENTS:
        return None
    try:
        uid = _oid(event.get("user_id"))
        uc = (event.get("metadata") or {}).get("user_closing")
        if uid is None or not isinstance(uc, (int, float)):
            return None
        m = await db.usermetas.find_one({"userId": uid}, {"availableBalance": 1})
        if not m:
            return None
        u = await db.users.find_one({"_id": uid}, {"clientname": 1})
        dbbal = float(m.get("availableBalance") or 0)
        if abs(dbbal - float(uc)) > EPS:
            return {"rule": "DB_BALANCE_MISMATCH", "severity": "HIGH",
                    "message": f"txn={event.get('transaction_id')}: event bola user_closing ₹{uc}, lekin DB me ASLI balance ₹{dbbal} (farak ₹{round(dbbal - float(uc), 2)}) — event jhooth ya beech me chhupa path chala. user='{(u or {}).get('clientname', '?')}'"}
        return None
    except Exception as e:
        print(f"⚠️ db rule skip: {e}")
        return None


DB_RULES = [rule_db_user_real, rule_db_closing_matches]