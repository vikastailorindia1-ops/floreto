# engine/invariants.py — AAPKE khud ke niyam
# Har invariant: event leta hai, finding (dict) ya None lautata hai

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


INVARIANTS = [invariant_financial_needs_amount, invariant_amount_positive]