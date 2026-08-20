# engine/real_rules.py — AAPKE asli events ke niyam (Phase 1: sirf event data)
import redis.asyncio as redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

MONEY_EVENTS = {"DEPOSIT_APPROVED", "WITHDRAWAL_PAID"}
EPS = 0.01  # float-dhool wala lesson (157791.94999999998)


async def rule_double_approval(event: dict) -> dict | None:
    """Same txn do baar approve = double credit — aapke bug family ka seedha detector."""
    if event.get("event_type") not in MONEY_EVENTS:
        return None
    txn = event.get("transaction_id")
    if not txn:
        return {"rule": "MONEY_EVENT_WITHOUT_TXN", "severity": "HIGH",
                "message": f"{event['event_type']} bina transaction_id! user={event.get('user_id')}"}
    first = await r.set(f"real:{event['event_type']}:{txn}", event["event_id"], nx=True, ex=7 * 86400)
    if not first:
        return {"rule": "DOUBLE_APPROVAL", "severity": "CRITICAL",
                "message": f"{event['event_type']} txn={txn} DO BAAR?! user={event.get('user_id')} amount={event.get('amount')}"}
    return None


async def rule_amount_sane(event: dict) -> dict | None:
    if event.get("event_type") not in MONEY_EVENTS:
        return None
    amt = event.get("amount")
    if amt is None or amt <= 0:
        return {"rule": "BAD_AMOUNT", "severity": "CRITICAL",
                "message": f"{event['event_type']} amount={amt}?! txn={event.get('transaction_id')}"}
    return None


async def rule_closing_not_negative(event: dict) -> dict | None:
    """Aapke asli closing balances ka live check — negative = impossible."""
    if event.get("event_type") not in MONEY_EVENTS:
        return None
    meta = event.get("metadata") or {}
    for k in ("agent_closing", "user_closing"):
        v = meta.get(k)
        if v is not None and v < -EPS:
            return {"rule": "NEGATIVE_CLOSING", "severity": "CRITICAL",
                    "message": f"{event['event_type']}: {k}={v} NEGATIVE! user={event.get('user_id')} txn={event.get('transaction_id')}"}
    return None


REAL_RULES = [rule_double_approval, rule_amount_sane, rule_closing_not_negative]