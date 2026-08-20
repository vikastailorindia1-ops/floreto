# engine/invariants.py — AAPKE khud ke niyam
from pymongo import AsyncMongoClient

# Game ke MongoDB se READ-ONLY connection (Security Data Access Layer)
mongo = AsyncMongoClient("mongodb://localhost:27017")
wallets = mongo.game.wallets
ledger = mongo.game.ledger

FINANCIAL_EVENTS = {"DEPOSIT", "WITHDRAWAL", "REWARD", "SETTLEMENT"}


async def invariant_financial_needs_amount(event: dict) -> dict | None:
    """Paise wala event bina amount ke? Impossible."""
    if event.get("event_type") in FINANCIAL_EVENTS and event.get("amount") is None:
        return {
            "rule": "INVARIANT_MISSING_AMOUNT",
            "severity": "HIGH",
            "message": f"{event.get('event_type')} bina amount ke! user={event.get('user_id')} txn={event.get('transaction_id')}",
        }
    return None


async def invariant_amount_positive(event: dict) -> dict | None:
    """Amount 0 ya negative? Paisa chhapne wala classic bug."""
    amt = event.get("amount")
    if event.get("event_type") in FINANCIAL_EVENTS and amt is not None and amt <= 0:
        return {
            "rule": "INVARIANT_NON_POSITIVE_AMOUNT",
            "severity": "CRITICAL",
            "message": f"{event.get('event_type')} amount={amt}?! user={event.get('user_id')} txn={event.get('transaction_id')}",
        }
    return None


async def invariant_balance_not_negative(event: dict) -> dict | None:
    """Event ke waqt user ka ASLI wallet padho — negative = impossible state."""
    if event.get("event_type") not in FINANCIAL_EVENTS:
        return None
    w = await wallets.find_one({"user_id": event.get("user_id")})
    if w and w.get("balance", 0) < 0:
        return {
            "rule": "INVARIANT_NEGATIVE_BALANCE",
            "severity": "CRITICAL",
            "message": f"user={event.get('user_id')} ka wallet balance {w['balance']}?! Impossible state. txn={event.get('transaction_id')}",
        }
    return None


async def invariant_ledger_matches_wallet(event: dict) -> dict | None:
    """Ledger ki saari entries ka jod == wallet balance. Mismatch = bhoot paisa."""
    if event.get("event_type") not in FINANCIAL_EVENTS:
        return None
    uid = event.get("user_id")
    w = await wallets.find_one({"user_id": uid})
    if not w:
        return None
    cursor = await ledger.aggregate([
        {"$match": {"user_id": uid}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ])
    rows = await cursor.to_list(length=1)
    ledger_total = rows[0]["total"] if rows else 0
    balance = w.get("balance", 0)
    if ledger_total != balance:
        diff = balance - ledger_total
        return {
            "rule": "INVARIANT_LEDGER_WALLET_MISMATCH",
            "severity": "CRITICAL",
            "message": f"user={uid}: wallet={balance} lekin ledger total={ledger_total} — ₹{diff} ka koi hisaab nahi! txn={event.get('transaction_id')}",
        }
    return None


INVARIANTS = [
    invariant_financial_needs_amount,
    invariant_amount_positive,
    invariant_balance_not_negative,
    invariant_ledger_matches_wallet,
]