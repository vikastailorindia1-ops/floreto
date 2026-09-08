# engine/real_rules.py — Rule #0: FLOW WHITELIST (default-deny) + jurm-detectors
import re

import redis.asyncio as redis
from engine.db_verify_rules import DB_RULES
from engine.flow_rules import FLOW_RULES

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

MONEY_EVENTS = {"DEPOSIT_APPROVED", "WITHDRAWAL_PAID"}
REQUEST_EVENTS = {"DEPOSIT_REQUESTED", "WITHDRAW_REQUESTED"}
EPS = 0.01
TTL = 7 * 86400

# ── AAPKA FLOW, letter-by-letter ──
OBJID = re.compile(r"^[0-9a-f]{24}$")             # Mongo ObjectId
TXN_FMT = {
    "DEPOSIT_REQUESTED":  re.compile(r"^D\d{12}$"),   # aapka generateTxnId: D+12 digits
    "DEPOSIT_APPROVED":   re.compile(r"^D\d{12}$"),
    "WITHDRAW_REQUESTED": re.compile(r"^W\d{12}$"),
    "WITHDRAWAL_PAID":    re.compile(r"^W\d{12}$"),
}

async def rule_flow_whitelist(event: dict) -> dict | None:
    """DEFAULT-DENY: jo aapke flow jaisa nahi — type/format/shape — wo alarm."""
    et = event.get("event_type")
    # TXN_STEP alag event hai — use flow_rules dekhta hai, whitelist nahi
    if event.get("event_type") == "TXN_STEP":
        return None
    if et not in TXN_FMT:
        return {"rule": "UNKNOWN_EVENT_TYPE", "severity": "HIGH",
                "message": f"'{et}' — aapke flow me aisa event hai hi NAHI. user={event.get('user_id')}"}
    txn = event.get("transaction_id")
    if not txn or not TXN_FMT[et].match(str(txn)):
        return {"rule": "MALFORMED_TXN_ID", "severity": "HIGH",
                "message": f"{et}: txn '{txn}' aapke format (D/W+12 digits) jaisa NAHI — flow ke bahar. user={event.get('user_id')}"}
    uid = event.get("user_id")
    if not uid or not OBJID.match(str(uid)):
        return {"rule": "MALFORMED_USER_ID", "severity": "HIGH",
                "message": f"{et} txn={txn}: user_id '{uid}' asli ObjectId NAHI — flow ke bahar."}
    meta = event.get("metadata") or {}
    agent = meta.get("agent_id")
    if not agent or not OBJID.match(str(agent)):
        return {"rule": "MALFORMED_AGENT_ID", "severity": "HIGH",
                "message": f"{et} txn={txn}: metadata.agent_id '{agent}' missing/galat — aapke emitter ka shape nahi."}
    for k in ("user_closing", "agent_closing", "bonus"):
        v = meta.get(k)
        if v is not None and not isinstance(v, (int, float)):
            return {"rule": "MALFORMED_FIELD", "severity": "HIGH",
                    "message": f"{et} txn={txn}: {k}='{v}' number nahi — shape violation."}
    return None


async def rule_track_requests(event: dict) -> dict | None:
    et = event.get("event_type")
    if et not in REQUEST_EVENTS:
        return None
    txn = event.get("transaction_id")
    if txn and event.get("amount") is not None:
        await r.set(f"req:{txn}", str(event["amount"]), ex=TTL)
    return None


async def rule_double_approval(event: dict) -> dict | None:
    if event.get("event_type") not in MONEY_EVENTS:
        return None
    txn = event.get("transaction_id")
    if not txn:
        return None
    first = await r.set(f"real:{event['event_type']}:{txn}", event["event_id"], nx=True, ex=TTL)
    if not first:
        return {"rule": "DOUBLE_APPROVAL", "severity": "CRITICAL",
                "message": f"{event['event_type']} txn={txn} DO BAAR?! user={event.get('user_id')} amount={event.get('amount')}"}
    return None


async def rule_amount_sane(event: dict) -> dict | None:
    if event.get("event_type") not in MONEY_EVENTS | REQUEST_EVENTS:
        return None
    amt = event.get("amount")
    if amt is None or amt <= 0:
        return {"rule": "BAD_AMOUNT", "severity": "CRITICAL",
                "message": f"{event['event_type']} amount={amt}?! txn={event.get('transaction_id')}"}
    return None


async def rule_closing_not_negative(event: dict) -> dict | None:
    if event.get("event_type") not in MONEY_EVENTS:
        return None
    meta = event.get("metadata") or {}
    for k in ("agent_closing", "user_closing"):
        v = meta.get(k)
        if v is not None and isinstance(v, (int, float)) and v < -EPS:
            return {"rule": "NEGATIVE_CLOSING", "severity": "CRITICAL",
                    "message": f"{event['event_type']}: {k}={v} NEGATIVE! user={event.get('user_id')} txn={event.get('transaction_id')}"}
    return None


async def rule_ghost_or_tampered_approval(event: dict) -> dict | None:
    et = event.get("event_type")
    if et not in MONEY_EVENTS:
        return None
    txn = event.get("transaction_id")
    if not txn:
        return None
    stored = await r.get(f"req:{txn}")
    if stored is None:
        return {"rule": "APPROVAL_WITHOUT_REQUEST", "severity": "MEDIUM",
                "message": f"{et} txn={txn} — iska request event kabhi nahi aaya (flow ke bahar, ya purana pending). user={event.get('user_id')}"}
    req_amt, appr = float(stored), float(event.get("amount") or 0)
    if abs(appr - req_amt) > EPS:
        return {"rule": "AMOUNT_CHANGED_AT_APPROVAL", "severity": "HIGH",
                "message": f"txn={txn}: request ₹{req_amt} thi, approve ₹{appr} hua (farak ₹{round(appr - req_amt, 2)}) user={event.get('user_id')}"}
    return None


async def rule_balance_chain(event: dict) -> dict | None:
    """UNKNOWN-BUG NET: closing ki kadi tooti = events ke bina paisa badla."""
    et = event.get("event_type")
    meta = event.get("metadata") or {}
    amt = float(event.get("amount") or 0)
    if et == "WITHDRAW_REQUESTED":
        for acc, delta in ((event.get("user_id"), -amt), (meta.get("agent_id"), +amt)):
            if acc:
                last = await r.get(f"bal:{acc}")
                if last is not None:
                    await r.set(f"bal:{acc}", str(float(last) + delta), ex=TTL)
        return None
    if et not in MONEY_EVENTS:
        return None
    bonus = float(meta.get("bonus") or 0)
    deltas = {"DEPOSIT_APPROVED": {"user": amt + bonus, "agent": -(amt + bonus)},
              "WITHDRAWAL_PAID": {"user": 0.0, "agent": 0.0}}[et]
    finding = None
    for acc, closing, delta, label in (
        (event.get("user_id"), meta.get("user_closing"), deltas["user"], "user"),
        (meta.get("agent_id"), meta.get("agent_closing"), deltas["agent"], "agent"),
    ):
        if not acc or not isinstance(closing, (int, float)):
            continue
        last = await r.get(f"bal:{acc}")
        if last is not None:
            expected = float(last) + delta
            jump = float(closing) - expected
            if abs(jump) > EPS and finding is None:
                finding = {"rule": "UNKNOWN_BALANCE_JUMP", "severity": "HIGH",
                           "message": f"{label} {acc}: expected ₹{round(expected,2)} lekin mila ₹{closing} — ₹{round(jump,2)} events ke BINA badla! (chhupa path/UNKNOWN BUG) txn={event.get('transaction_id')}"}
        await r.set(f"bal:{acc}", str(closing), ex=TTL)
    return finding


BONUS_MAX_PCT = 100  # AAPKI policy

async def rule_bonus_policy(event: dict) -> dict | None:
    """AAPKA rule: bonus policy-cap ke upar = backend guard bypass."""
    if event.get("event_type") != "DEPOSIT_APPROVED":
        return None
    amt = float(event.get("amount") or 0)
    bonus = float((event.get("metadata") or {}).get("bonus") or 0)
    if amt <= 0 or bonus <= 0:
        return None
    pct = bonus / amt * 100
    if pct > BONUS_MAX_PCT + EPS:
        return {"rule": "BONUS_ABOVE_HARD_CAP", "severity": "CRITICAL",
                "message": f"txn={event.get('transaction_id')}: bonus ₹{bonus} = {round(pct,1)}% of ₹{amt} — cap ke UPAR?! user={event.get('user_id')}"}
    return None


REAL_RULES = [rule_flow_whitelist, rule_track_requests, rule_double_approval,
              rule_amount_sane, rule_closing_not_negative,
              rule_ghost_or_tampered_approval, rule_bonus_policy] + DB_RULES + FLOW_RULES

