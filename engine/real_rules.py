# engine/real_rules.py — AAPKE asli events ke niyam
import redis.asyncio as redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

MONEY_EVENTS = {"DEPOSIT_APPROVED", "WITHDRAWAL_PAID"}
REQUEST_EVENTS = {"DEPOSIT_REQUESTED", "WITHDRAW_REQUESTED"}
EPS = 0.01
TTL = 7 * 86400


async def rule_track_requests(event: dict) -> dict | None:
    """REQUESTED events yaad rakho — flow-sequence checks inhi par khade hain."""
    et = event.get("event_type")
    if et not in REQUEST_EVENTS:
        return None
    txn = event.get("transaction_id")
    if not txn:
        return {"rule": "REQUEST_WITHOUT_TXN", "severity": "HIGH",
                "message": f"{et} bina transaction_id! user={event.get('user_id')}"}
    if event.get("amount") is not None:
        await r.set(f"req:{txn}", str(event["amount"]), ex=TTL)
    return None


async def rule_double_approval(event: dict) -> dict | None:
    if event.get("event_type") not in MONEY_EVENTS:
        return None
    txn = event.get("transaction_id")
    if not txn:
        return {"rule": "MONEY_EVENT_WITHOUT_TXN", "severity": "HIGH",
                "message": f"{event['event_type']} bina transaction_id! user={event.get('user_id')}"}
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
        if v is not None and v < -EPS:
            return {"rule": "NEGATIVE_CLOSING", "severity": "CRITICAL",
                    "message": f"{event['event_type']}: {k}={v} NEGATIVE! user={event.get('user_id')} txn={event.get('transaction_id')}"}
    return None


async def rule_ghost_or_tampered_approval(event: dict) -> dict | None:
    """Flow ke bahar: approval bina request = GHOST; amount badla = TAMPERED."""
    et = event.get("event_type")
    if et not in MONEY_EVENTS:
        return None
    txn = event.get("transaction_id")
    if not txn:
        return None
    stored = await r.get(f"req:{txn}")
    if stored is None:
        return {"rule": "APPROVAL_WITHOUT_REQUEST", "severity": "MEDIUM",
                "message": f"{et} txn={txn} — iska request event kabhi nahi aaya (flow ke bahar, ya emitter se purana pending). user={event.get('user_id')}"}
    req_amt, appr = float(stored), float(event.get("amount") or 0)
    if abs(appr - req_amt) > EPS:
        return {"rule": "AMOUNT_CHANGED_AT_APPROVAL", "severity": "HIGH",
                "message": f"txn={txn}: request ₹{req_amt} thi, approve ₹{appr} hua (farak ₹{round(appr - req_amt, 2)}) user={event.get('user_id')}"}
    return None


REAL_RULES = [rule_track_requests, rule_double_approval, rule_amount_sane,
              rule_closing_not_negative, rule_ghost_or_tampered_approval]