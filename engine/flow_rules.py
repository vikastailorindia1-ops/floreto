# engine/flow_rules.py — depositsuccess ka poora step-monitor + AI double-layer
import json

import redis.asyncio as redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
TTL = 7 * 86400

# har flow ka POORA step-order + final event
FLOWS = {
    "DEPOSIT_APPROVE": {
        "steps": ["GUARDS_PASSED", "AGENT_DEBITED", "USER_CREDITED",
                  "STATEMENTS_WRITTEN", "SUCCESS_RECORDED"],
        "final": "DEPOSIT_APPROVED",
    },
}
FINAL_TO_FLOW = {v["final"]: k for k, v in FLOWS.items()}


async def rule_flow_steps(event: dict) -> dict | None:
    et = event.get("event_type")

    # ── STEP event: record + order check ──
    if et == "TXN_STEP":
        meta = event.get("metadata") or {}
        flow, step, txn = meta.get("flow"), meta.get("step"), event.get("transaction_id")
        spec = FLOWS.get(flow)
        if not spec or not txn or step not in spec["steps"]:
            return {"rule": "UNKNOWN_STEP", "severity": "HIGH",
                    "message": f"TXN_STEP anjaan: flow={flow} step={step} txn={txn}"}
        key = f"flow:{txn}"
        done = json.loads(await r.get(key) or "[]")
        if step in done:
            return {"rule": "STEP_REPEATED", "severity": "CRITICAL",
                    "message": f"txn={txn} ({flow}): step '{step}' DO BAAR — retry/duplicate money-move?"}
        idx = spec["steps"].index(step)
        missing = [s for s in spec["steps"][:idx] if s not in done]
        done.append(step)
        await r.set(key, json.dumps(done), ex=TTL)
        if missing:
            return {"rule": "STEP_OUT_OF_ORDER", "severity": "CRITICAL",
                    "message": f"txn={txn} ({flow}): '{step}' aaya lekin {missing} abhi tak nahi — flow ke bahar/galat order!"}
        return None

    # ── FINAL event: saare steps poore hue? ──
    if et in FINAL_TO_FLOW:
        flow = FINAL_TO_FLOW[et]
        txn = event.get("transaction_id")
        if not txn:
            return None
        key = f"flow:{txn}"
        done = json.loads(await r.get(key) or "[]")
        required = FLOWS[flow]["steps"]
        missing = [s for s in required if s not in done]
        await r.delete(key)
        # self-deposit chhoot: agent==user pe AGENT_DEBITED nahi aata
        meta = event.get("metadata") or {}
        if flow == "DEPOSIT_APPROVE" and str(event.get("user_id")) == str(meta.get("agent_id")):
            missing = [s for s in missing if s != "AGENT_DEBITED"]
        if missing:
            return {"rule": "STEPS_MISSING_AT_FINAL", "severity": "CRITICAL",
                    "message": f"{et} txn={txn}: final aa gaya par ye steps kabhi nahi aaye {missing} — chhupa path/adhoora flow!"}
        return None

    return None


FLOW_RULES = [rule_flow_steps]