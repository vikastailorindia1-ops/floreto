# engine/db_rules.py — DB-VERIFIED checks: event ka jhooth vs Atlas ka sach
import os

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import AsyncMongoClient

load_dotenv()
GAME_URI = os.getenv("GAME_MONGO_URI", "")
GAME_DB = os.getenv("GAME_MONGO_DB", "")

_client = AsyncMongoClient(GAME_URI, serverSelectionTimeoutMS=5000) if GAME_URI else None
_raw_db = _client[GAME_DB] if (_client is not None and GAME_DB) else None


_ALLOWED_READS = {
    "find", "find_one", "count_documents", "estimated_document_count",
    "distinct", "aggregate", "watch",
}


class _SafeCollection:
    def __init__(self, coll, name):
        self._coll = coll
        self._name = name

    def __getattr__(self, method):
        if method in _ALLOWED_READS:
            return getattr(self._coll, method)
        def _blocked(*args, **kwargs):
            raise PermissionError(
                f"SAFETY GATE: '{method}' BLOCK - security engine sirf READ kar sakta hai "
                f"(collection: {self._name}).")
        return _blocked


class _SafeDB:
    def __init__(self, db):
        self._db = db

    def __getattr__(self, coll_name):
        return _SafeCollection(getattr(self._db, coll_name), coll_name)

    def __getitem__(self, coll_name):
        return _SafeCollection(self._db[coll_name], coll_name)


db = _SafeDB(_raw_db) if _raw_db is not None else None


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


async def rule_db_duplicate_utr(event: dict) -> dict | None:
    """Same UTR do baar? Ek bank-payment do baar bhunaya ja raha — fraud."""
    if db is None or event.get("event_type") != "DEPOSIT_APPROVED":
        return None
    try:
        meta = event.get("metadata") or {}
        utr = meta.get("utr") or meta.get("utrNumber")
        if not utr:
            return None
        # normalize wahi jaise backend karta hai
        utr_norm = str(utr).strip().upper().replace(" ", "")
        matches = await db.depositsuccesses.count_documents({"utrNumber": utr_norm})
        if matches > 1:  # 1 = ye khud; 2+ = duplicate
            return {"rule": "DUPLICATE_UTR", "severity": "CRITICAL",
                    "message": f"UTR '{utr_norm}' DB me {matches} baar hai! Ek bank-payment ko multiple deposits me bhuna raha — txn={event.get('transaction_id')} user={event.get('user_id')}"}
        return None
    except Exception as e:
        print(f"⚠️ db rule skip: {e}")
        return None


async def rule_db_utr_belongs_elsewhere(event: dict) -> dict | None:
    """Ye UTR kisi DOOSRE user ke deposit me to nahi? Stolen UTR."""
    if db is None or event.get("event_type") != "DEPOSIT_APPROVED":
        return None
    try:
        meta = event.get("metadata") or {}
        utr = meta.get("utr") or meta.get("utrNumber")
        uid = _oid(event.get("user_id"))
        if not utr or uid is None:
            return None
        utr_norm = str(utr).strip().upper().replace(" ", "")
        other = await db.depositsuccesses.find_one(
            {"utrNumber": utr_norm, "userId": {"$ne": uid}},
            {"clientname": 1})
        if other:
            return {"rule": "UTR_STOLEN", "severity": "CRITICAL",
                    "message": f"UTR '{utr_norm}' pehle se kisi AUR user ('{other.get('clientname')}') ke deposit me use hui — chori/reuse! txn={event.get('transaction_id')}"}
        return None
    except Exception as e:
        print(f"⚠️ db rule skip: {e}")
        return None


async def rule_db_utr_reused_at_request(event: dict) -> dict | None:
    """DEPOSIT_REQUESTED: is UTR se pehle bhi koi request/success to nahi? Request time pe hi pakdo."""
    if db is None or event.get("event_type") != "DEPOSIT_REQUESTED":
        return None
    try:
        meta = event.get("metadata") or {}
        utr = meta.get("utr")
        if not utr:
            return None
        utr_norm = str(utr).strip().upper().replace(" ", "")
        # DB me pehle se koi approved deposit is UTR se?
        in_success = await db.depositsuccesses.count_documents({"utrNumber": utr_norm})
        # ya koi aur pending/approved request (khud ke alawa)?
        this_txn = event.get("transaction_id")
        in_requests = await db.depositrequests.count_documents({
            "utrNumber": utr_norm,
            "txnId": {"$ne": this_txn},
            "status": {"$in": ["pending", "approved"]},
        })
        if in_success > 0 or in_requests > 0:
            return {"rule": "UTR_REUSED_AT_REQUEST", "severity": "CRITICAL",
                    "message": f"DEPOSIT_REQUESTED txn={this_txn}: UTR '{utr_norm}' pehle se use ho chuka hai (approved: {in_success}, pending/other-req: {in_requests})! Game ka UTR-guard bypass hua — duplicate deposit request bani. user={event.get('user_id')}"}
        return None
    except Exception as e:
        print(f"⚠️ db rule skip: {e}")
        return None


DB_RULES = [rule_db_user_real,
            rule_db_duplicate_utr, rule_db_utr_belongs_elsewhere, rule_db_utr_reused_at_request]
