# ai/chatbot/query_runner.py — plan ko DB pe chalata hai (read-only, safety-gate se)
import re as _re
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from engine.db_verify_rules import db, _oid
from ai.chatbot.knowledge import ALLOWED_COLLECTIONS, BLOCKED_FIELDS


IST = timezone(timedelta(hours=5, minutes=30))  # India time


def _clean_val(v):
    """ObjectId/date/nested sab ko JSON-safe banao (recursive). Date -> IST me."""
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        # DB me UTC hai (ya bina tz); IST me dikhao
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(IST).strftime("%d-%b-%Y %H:%M")
    if isinstance(v, dict):
        return {k: _clean_val(x) for k, x in v.items() if k not in BLOCKED_FIELDS}
    if isinstance(v, (list, tuple)):
        return [_clean_val(x) for x in v]
    return v


def _strip(doc: dict) -> dict:
    """password/hash fields hatao, sab kuch JSON-safe banao (nested bhi)."""
    return {k: _clean_val(v) for k, v in doc.items() if k not in BLOCKED_FIELDS}


async def _find_one_user(ref):
    """naam ya id se user dhundo. EXACT match hi. Partial pe suggestions deta hai."""
    oid = _oid(ref)
    if oid:
        u = await db.users.find_one({"_id": oid}, {"clientname": 1})
        return {"user": u} if u else {"error": f"ID '{ref}' ka koi user nahi mila."}

    esc_ref = _re.escape(ref)
    # 1) exact (case-insensitive)
    u = await db.users.find_one({"clientname": {"$regex": f"^{esc_ref}$", "$options": "i"}}, {"clientname": 1})
    if u:
        return {"user": u}

    # 2) space/dash hata ke ("user 2" -> "user2")
    tight = _re.sub(r"[\s\-_]+", "", ref)
    u = await db.users.find_one({"clientname": {"$regex": f"^{_re.escape(tight)}$", "$options": "i"}}, {"clientname": 1})
    if u:
        return {"user": u}

    # 3) exact nahi mila -> milte-julte naam SUGGEST karo (utha mat lo!)
    matches = []
    cur = db.users.find({"clientname": {"$regex": _re.escape(tight), "$options": "i"}},
                        {"clientname": 1}).limit(10)
    async for d in cur:
        matches.append(d.get("clientname"))

    if len(matches) == 1:
        u = await db.users.find_one({"clientname": matches[0]}, {"clientname": 1})
        return {"user": u}
    if matches:
        return {"error": f"'{ref}' naam ka exact user nahi mila. Ye mile: {', '.join(matches)}. "
                         f"Poora naam batao."}
    return {"error": f"'{ref}' naam/id ka koi user DB me nahi mila."}


def _summarize(rows):
    """har numeric field ka total/avg/min/max — server-side (lakhon rows pe bhi sahi)."""
    totals = {}
    for r in rows:
        for k, v in r.items():
            if isinstance(v, bool) or k in ("__v", "_id", "userId"):
                continue
            if isinstance(v, (int, float)):
                t = totals.setdefault(k, {"sum": 0, "count": 0, "min": v, "max": v})
                t["sum"] += v
                t["count"] += 1
                t["min"] = min(t["min"], v)
                t["max"] = max(t["max"], v)
    return {k: {"total": round(t["sum"], 2), "avg": round(t["sum"] / t["count"], 2),
                "min": t["min"], "max": t["max"], "entries": t["count"]}
            for k, t in totals.items()}


async def run_plan(plan: dict) -> dict:
    coll_name = plan.get("collection", "")
    if coll_name not in ALLOWED_COLLECTIONS:
        return {"error": f"'{coll_name}' collection allowed nahi."}

    # 1) user(s) dhundo — ek ya kai
    filt = {}
    user_name = None

    refs = plan.get("find_users")
    if not refs:
        one = (plan.get("find_user") or "").strip()
        refs = [one] if one else []
    refs = [str(r).strip() for r in refs if str(r).strip()]

    uids, names = [], []
    for r in refs:
        res = await _find_one_user(r)
        if res.get("error"):
            return {"error": res["error"]}
        u = res["user"]
        uids.append(u["_id"])
        names.append(u.get("clientname"))

    if uids:
        key = "_id" if coll_name == "users" else "userId"
        filt = {key: uids[0]} if len(uids) == 1 else {key: {"$in": uids}}
        user_name = names[0] if len(names) == 1 else ", ".join(names)

    # HIERARCHY (a): sirf DIRECT children
    parent_ref = (plan.get("parent_of") or "").strip()
    if parent_ref:
        pres = await _find_one_user(parent_ref)
        if pres.get("error"):
            return {"error": pres["error"]}
        parent = pres["user"]
        filt["parentId"] = parent["_id"]
        user_name = f"{parent.get('clientname')} ke direct neeche"

    # HIERARCHY (b): POORI TREE — children + unke children + aage tak
    tree_ref = (plan.get("tree_of") or "").strip()
    tree_names_by_id = {}   # rank/group ke liye chahiye
    if tree_ref:
        tres = await _find_one_user(tree_ref)
        if tres.get("error"):
            return {"error": tres["error"]}
        root = tres["user"]
        all_ids, frontier, seen = [], [root["_id"]], {str(root["_id"])}
        depth = 0
        while frontier and depth < 12:          # 12 level tak (loop-safe)
            kids = []
            cur_k = db.users.find({"parentId": {"$in": frontier}}, {"_id": 1, "clientname": 1})
            async for k in cur_k:
                kid = k["_id"]
                if str(kid) in seen:
                    continue
                seen.add(str(kid))
                kids.append(kid)
                all_ids.append(kid)
                tree_names_by_id[str(kid)] = k.get("clientname", "?")
            frontier = kids
            depth += 1
        if not all_ids:
            return {"error": f"'{root.get('clientname')}' ke neeche koi nahi mila."}
        key = "_id" if coll_name == "users" else "userId"
        filt[key] = {"$in": all_ids}
        user_name = f"{root.get('clientname')} ki tree ({len(all_ids)} log)"

    # 2) extra filter + date
    filt.update(plan.get("extra_filter") or {})
    days = int(plan.get("days", 0) or 0)
    date_from = (plan.get("date_from") or "").strip()
    date_to = (plan.get("date_to") or "").strip()

    hour_from = int(plan.get("hour_from", 0) or 0)
    hour_to = int(plan.get("hour_to", 0) or 0)
    if date_from or date_to:
        try:
            if date_from:
                datetime.strptime(date_from, "%Y-%m-%d")
            if date_to:
                datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            return {"error": f"Ye date galat hai ({date_from or date_to}) — aisi date hoti nahi. Sahi date batao."}
    if date_from or date_to:
        dfilt = {}
        # date user ne IST me boli — IST midnight se UTC me convert karo
        if date_from:
            d = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=IST)
            if hour_from > 0:
                d = d.replace(hour=hour_from)
            dfilt["$gte"] = d.astimezone(timezone.utc)
        if date_to:
            d = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=IST)
            # agar hour_to diya to date_from ki hi date pe wo hour tak (same day range)
            if hour_to > 0 and date_from:
                d = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=IST, hour=hour_to)
            dfilt["$lt"] = d.astimezone(timezone.utc)
        # activitylogs me date field "date" hai, baaki me "createdAt"
        date_key = "date" if coll_name == "activitylogs" else "createdAt"
        filt[date_key] = dfilt
    else:
        hours_ago = int(plan.get("hours_ago", 0) or 0)
        minutes_ago = int(plan.get("minutes_ago", 0) or 0)
        if days > 0 or hours_ago > 0 or minutes_ago > 0:
            since = datetime.now(timezone.utc) - timedelta(days=days, hours=hours_ago, minutes=minutes_ago)
            # bets me placedAt aur createdAt dono ho sakte hain — dono me se jo mile
            if coll_name == "bets":
                filt["$or"] = [{"placedAt": {"$gte": since}}, {"createdAt": {"$gte": since}}]
            else:
                filt["createdAt"] = {"$gte": since}

    # 3) query (read-only, safety-gate se) — koi limit nahi jab tak plan na kahe
    coll = db[coll_name]
    limit = int(plan.get("limit", 0) or 0)
    # sort direction: newest first (-1) default, oldest first (+1) jab "sabse pehle" pucha ho
    sort_field = "date" if coll_name == "activitylogs" else "createdAt"
    sort_dir = -1 if plan.get("sort_newest", True) else 1
    cur = coll.find(filt).sort(sort_field, sort_dir)
    if limit > 0:
        cur = cur.limit(limit)

    name_by_id = {str(i): n for i, n in zip(uids, names)}
    name_by_id.update(tree_names_by_id)  # tree wale bhi
    rows = []
    unknown_uids = set()   # jinke naam nahi hain, baad me ek shot me nikaalenge
    async for d in cur:
        row = _strip(d)
        rid = str(row.get("userId") or row.get("_id") or "")
        if rid in name_by_id:
            row["_user"] = name_by_id[rid]
        elif rid and rid != "None":
            unknown_uids.add(rid)
        rows.append(row)

    # jinke naam nahi mile — ek $in query me sab uthao
    if unknown_uids:
        oids = []
        for s in unknown_uids:
            try:
                oids.append(ObjectId(s))
            except Exception:
                pass
        if oids:
            async for u in db.users.find({"_id": {"$in": oids}}, {"clientname": 1}):
                name_by_id[str(u["_id"])] = u.get("clientname", "?")
            # rows me bhar do
            for r in rows:
                rid = str(r.get("userId") or r.get("_id") or "")
                if rid in name_by_id and "_user" not in r:
                    r["_user"] = name_by_id[rid]

    # 🏆 RANKING (agar maanga ho): per-user group + sort
    ranking = None
    rank_field = (plan.get("rank_by") or "").strip()
    if rank_field and plan.get("group_by_user"):
        per_user = {}  # user -> {total, count, entries}
        for r in rows:
            uname = r.get("_user") or r.get("clientname") or str(r.get("userId", "?"))
            v = r.get(rank_field)
            if not isinstance(v, (int, float)):
                continue
            g = per_user.setdefault(uname, {"total": 0.0, "count": 0})
            g["total"] += float(v)
            g["count"] += 1
        order = plan.get("rank_order", "desc")
        rank_list = sorted(per_user.items(), key=lambda x: x[1]["total"],
                           reverse=(order != "asc"))
        top_n = int(plan.get("limit", 0) or 10) or 10
        ranking = [{"user": u, "total": round(g["total"], 2), "entries": g["count"]}
                   for u, g in rank_list[:top_n]]

    # PEAK dates — numeric fields ke MAX + MIN wale rows nikaalo (Qwen ko ready mil jaye)
    peaks = {}
    def _row_context(r):
        return {
            "date": r.get("createdAt") or r.get("placedAt") or "?",
            "user": r.get("_user") or r.get("clientname"),
            "remark": (r.get("remark") or "")[:80],
            "transactionType": r.get("transactionType"),
            "actionType": r.get("actionType"),
            "fromUser": r.get("fromUser"),
            "toUser": r.get("toUser"),
            "credit": r.get("credit"),
            "debit": r.get("debit"),
        }
    for field in ("closing", "profitLoss", "stake", "amount"):
        max_row, max_val, min_row, min_val = None, None, None, None
        for r in rows:
            v = r.get(field)
            if not isinstance(v, (int, float)):
                continue
            if max_val is None or v > max_val:
                max_val, max_row = v, r
            if min_val is None or v < min_val:
                min_val, min_row = v, r
        if max_row is not None:
            peaks[f"max_{field}"] = {"value": max_val, **_row_context(max_row)}
            peaks[f"min_{field}"] = {"value": min_val, **_row_context(min_row)}

    return {"user": user_name, "collection": coll_name, "count": len(rows),
            "want_list": bool(plan.get("want_list", True)),
            "summary": _summarize(rows),
            "peaks": peaks,
            "ranking": ranking,
            "rank_by": rank_field or None,
            "filter_used": {k: str(v) for k, v in filt.items()}, "rows": rows}


# ── Deposit/Withdraw ka poora hisaab — charon collections ek saath ──
DW_COLLECTIONS = {
    "pending_deposits": ("depositrequests", {"status": "pending"}),
    "pending_withdrawals": ("withdrawrequests", {"status": "pending"}),
    "declined_deposits": ("depositrequests", {"status": "declined"}),
    "declined_withdrawals": ("withdrawrequests", {"status": "declined"}),
    "success_deposits": ("depositsuccesses", {}),
    "success_withdrawals": ("withdrawalsuccesses", {}),
}


async def run_dw_summary(ref: str, plan: dict) -> dict:
    res = await _find_one_user(ref)
    if res.get("error"):
        return {"error": res["error"]}
    uid = res["user"]["_id"]

    full = await db.users.find_one({"_id": uid},
                                   {"clientname": 1, "AccountTypecheck": 1,
                                    "isSelfRegistered": 1, "isAutodw": 1})
    who = full.get("clientname")

    # 👥 KISKI requests? Agar Agent/Master/SuperAdmin hai to uske NEECHE ke sab users ki.
    #    (Agent khud request nahi karta — uske clients karte hain.)
    role = str(full.get("AccountTypecheck") or "")
    target_ids = [uid]
    scope = who
    if role and role != "User":
        tree, frontier, seen = [], [uid], {str(uid)}
        depth = 0
        while frontier and depth < 12:
            kids = []
            async for k in db.users.find({"parentId": {"$in": frontier}}, {"_id": 1}):
                if str(k["_id"]) in seen:
                    continue
                seen.add(str(k["_id"]))
                kids.append(k["_id"])
                tree.append(k["_id"])
            frontier = kids
            depth += 1
        if tree:
            target_ids = tree
            scope = f"{who} ke neeche ({len(tree)} log)"

    # ⚡ FAST-SKIP: sirf single User pe — dono flags false = D/W karta hi nahi
    if role == "User" and not full.get("isSelfRegistered") and not full.get("isAutodw"):
        return {"user": who, "collection": "deposit/withdraw",
                "count": 0, "want_list": False, "summary": {}, "rows": [],
                "note": f"{who} ka isSelfRegistered aur isAutodw dono false hain — "
                        f"ye user deposit/withdraw karta hi nahi."}

    # date/time filter (agar diya ho)
    dfilt = {}
    days = int(plan.get("days", 0) or 0)
    hours_ago = int(plan.get("hours_ago", 0) or 0)
    minutes_ago = int(plan.get("minutes_ago", 0) or 0)
    date_from, date_to = (plan.get("date_from") or "").strip(), (plan.get("date_to") or "").strip()
    hour_from = int(plan.get("hour_from", 0) or 0)
    hour_to = int(plan.get("hour_to", 0) or 0)
    # galat date (jaise 30 Feb) pe crash na ho — polite error do
    if date_from or date_to:
        try:
            if date_from:
                datetime.strptime(date_from, "%Y-%m-%d")
            if date_to:
                datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            return {"error": f"Ye date galat hai ({date_from or date_to}) — aisi date hoti nahi. Sahi date batao."}
    if date_from or date_to:
        d = {}
        if date_from:
            dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=IST)
            if hour_from > 0:
                dt = dt.replace(hour=hour_from)
            d["$gte"] = dt.astimezone(timezone.utc)
        if date_to:
            dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=IST)
            if hour_to > 0 and date_from:
                dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=IST, hour=hour_to)
            d["$lt"] = dt.astimezone(timezone.utc)
        dfilt["createdAt"] = d
    elif days > 0 or hours_ago > 0 or minutes_ago > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days, hours=hours_ago, minutes=minutes_ago)
        dfilt["createdAt"] = {"$gte": since}

    # Filter: (userId tree me hai) YA (approvedBy = ye admin/agent)
    # — matlab: uske neeche ke users ki requests + uske khud approve kiye hue, dono
    if role and role != "User":
        id_filter = {"$or": [
            {"userId": {"$in": target_ids}},
            {"approvedBy": who},   # jo naam se approved hain
        ]}
    else:
        id_filter = {"userId": target_ids[0]}

    # user ne KYA maanga — sirf wahi collections chalao
    only = (plan.get("dw_only") or "all").strip()
    WANT = {
        "pending": {"pending_deposits", "pending_withdrawals"},
        "pending_deposit": {"pending_deposits"},
        "pending_withdraw": {"pending_withdrawals"},
        "success": {"success_deposits", "success_withdrawals"},
        "success_deposit": {"success_deposits"},
        "success_withdraw": {"success_withdrawals"},
        "declined": {"declined_deposits", "declined_withdrawals"},
        "declined_deposit": {"declined_deposits"},
        "declined_withdraw": {"declined_withdrawals"},
        "all": set(DW_COLLECTIONS.keys()),
    }.get(only, set(DW_COLLECTIONS.keys()))

    parts, all_rows = {}, []
    for label, (coll_name, extra) in DW_COLLECTIONS.items():
        if label not in WANT:
            continue
        rows = []
        async for d in db[coll_name].find({**id_filter, **extra, **dfilt}).sort("createdAt", -1):
            row = _strip(d)
            row["_kind"] = label
            rows.append(row)
        parts[label] = {"count": len(rows),
                        "total_amount": round(sum(float(r.get("amount") or 0) for r in rows), 2)}
        all_rows.extend(rows)

    return {"user": scope, "collection": "deposit/withdraw",
            "count": len(all_rows), "want_list": bool(plan.get("want_list", True)),
            "summary": parts, "filter_used": {k: str(v) for k, v in dfilt.items()},
            "rows": all_rows}