# ai/chatbot/chat_api.py — AI Investigator API (gyaan knowledge.py me, query query_runner.py me)
import json
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel

from engine.db_verify_rules import db
from ai.chatbot.knowledge import PLANNER_PROMPT, ANSWER_PROMPT, GREETING_PROMPT
from ai.chatbot.query_runner import run_plan, run_dw_summary

qwen = AsyncOpenAI(base_url="http://localhost:8000/v1", api_key="none")
MODEL = "qwen3.6-27b"

app = FastAPI(title="AI Investigator Chatbot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # production me apni website ka domain daalo
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatTurn(BaseModel):
    role: str
    text: str


class ChatMsg(BaseModel):
    message: str
    history: list[ChatTurn] = []


async def _ask(system: str, user: str, max_tokens=None, temp=0.0, want_json=False) -> str:
    # ⚡ max_tokens=None -> koi limit nahi
    kw = {"model": MODEL, "temperature": temp,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if max_tokens:
        kw["max_tokens"] = max_tokens
    # 🚀 thinking OFF — seedha jawab, soch ka time bachao (4-5x speed)
          # 🚀 thinking OFF sirf JSON-planner me (wahi sabse slow tha) —
        #    answer me thinking ON (naam/data bilkul sahi aayen, hallucination na ho)
        if want_json:
            kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        r = await qwen.chat.completions.create(**kw)
    msg = r.choices[0].message
    out = (msg.content or "").strip()
    if out:
        return out

    # content khali -> reasoning me dekh
    reasoning = (getattr(msg, "reasoning_content", None) or
                getattr(msg, "reasoning", None) or "").strip()
    if not reasoning:
        return ""

    import re as _re
    if want_json:
        # planner ke liye — JSON kahin bhi ho, dhundo
        # pehle reasoning me, phir content me (agar content ho par usme JSON nahi tha)
        for text in (reasoning, msg.content or ""):
            # array pehle ({...} pehle mil ke choti object miss ho sakti hai)
            for pattern in (r"\[[\s\S]*?\](?=\s*$|\s*[^,\]]|\s*```)",
                        r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"):
                for m in _re.finditer(pattern, text):
                    candidate = m.group(0)
                    # JSON valid hai check karo
                    try:
                        import json as _json
                        parsed = _json.loads(candidate)
                        if isinstance(parsed, (dict, list)) and (
                            (isinstance(parsed, dict) and "collection" in parsed) or
                            (isinstance(parsed, list) and len(parsed) > 0)
                        ):
                            return candidate
                    except Exception:
                        continue
        # last resort — jo bhi {...} ya [...] mila wahi de do
        m = _re.search(r"\[[\s\S]*\]|\{[\s\S]*\}", reasoning + (msg.content or ""), _re.DOTALL)
        return m.group(0) if m else ""

    # answer ke liye — reasoning me se ASLI jawab nikaalo (soch ka kachra hataao)
    # 1) Quoted "..." wale strings dekho — Qwen inhi me final answer daalta hai
    quotes = _re.findall(r'"([^"]{5,200})"', reasoning)
    if quotes:
        # sabse chhota unique quote lo (usually final answer)
        clean = [q for q in quotes if not q.startswith(("I'll", "I ", "Let", "Final", "Output",
                                                        "Self", "Wait", "Proceeds", "Done",
                                                        "Check", "Draft"))]
        if clean:
            # sabse zyada baar aaya hua = actual answer (jaise "Is user ke liye...")
            from collections import Counter
            most_common = Counter(clean).most_common(1)[0][0]
            return most_common.strip()
    return ""


@app.post("/chat")
async def chat(m: ChatMsg):
    if db is None:
        return {"reply": "⚠️ DB connect nahi.", "data": None}

    # 1) Qwen se plan banwao — history saath me (context ke liye)
    ctx = ""
    if m.history:
        lines = []
        for h in m.history[-8:]:   # sirf pichhle 4 turns
            who = "User" if h.role == "user" else "Bot"
            lines.append(f"{who}: {h.text}")
        ctx = "PICHHLI BAAT-CHEET (context ke liye, jab user 'uski/wahi/us user' bole to yahin se samjho):\n" + "\n".join(lines) + "\n\n"

    try:
        # ⚡ max_tokens=8000 -> reasoning + JSON dono ke liye kaafi hai
        raw = (await _ask(PLANNER_PROMPT, ctx + "NAYA SAWAAL: " + m.message,
                        max_tokens=6000, want_json=True)).replace("```json", "").replace("```", "")
        # multi-query array SIRF tab jab raw '[' se shuru ho (JSON ke andar
        # wale chhote arrays jaise ["selfregsa"] ko galti se na pakde)
        stripped = raw.strip()
        if stripped.startswith("["):
            plans = json.loads(re.search(r"\[[\s\S]*\]", stripped).group(0))
            if not isinstance(plans, list):
                plans = [plans]
        else:
            obj_match = re.search(r"\{[\s\S]*\}", raw)
            plans = [json.loads(obj_match.group(0) if obj_match else raw)]
        # safety: sirf dict rakho, string/kachra hataao
        plans = [p for p in plans if isinstance(p, dict)]
        if not plans:
            raise ValueError("Koi valid plan nahi mila")
    except Exception as e:
        return {"reply": "⚠️ Sawaal samajh nahi aaya, thoda simple shabdon me dobara poochho.",
                "data": None, "debug": str(e)[:100]}

    # 2) Plans chalao (multi-query support — deposit + withdrawal ek saath, etc.)
    results = []
    for p in plans:
        # greeting/casual — skip
        if not p.get("collection") and not p.get("dw_summary") \
        and not p.get("parent_of") and not p.get("tree_of"):
            continue
        dw_ref = (p.get("dw_summary") or "").strip()
        res = await run_dw_summary(dw_ref, p) if dw_ref else await run_plan(p)
        if res.get("error"):
            return {"reply": f"❌ {res['error']}", "data": None}
        results.append(res)

    # 3) Sirf greeting/casual tha to
    if not results:
        try:
            return {"reply": await _ask(GREETING_PROMPT, ctx + "NAYA SAWAAL: " + m.message, None, 0.5) or "Namaste!", "data": None}
        except Exception:
            return {"reply": "Namaste! 🕵️ Kisi user ka balance, statement, deposits ya bets poochho.", "data": None}

    result = results[0]   # widget ke liye pehla result

    # 4) Qwen se jawab banwao (totals server ne calculate kiye)
    try:
        # multi-query hai to sab results ka combined info bhejo
        combined_info = ""
        if len(results) > 1:
            for i, r in enumerate(results, 1):
                combined_info += f"\n--- Query {i} ({r.get('collection', '?')}) ---\n"
                combined_info += f"Count: {r['count']}, Summary: {json.dumps(r.get('summary', {}), default=str)}\n"
        rank_block = ""
        if result.get("ranking"):
            rank_block = (f"\n\nRANKING (server ne per-user group kiya, {result['rank_by']} ke hisaab se, "
                        f"top {len(result['ranking'])}):\n{json.dumps(result['ranking'], default=str)}\n")
        if result.get("peaks"):
            # user ke sawaal me "kam/lowest/chhota" hai -> sirf min_* bhejo
            q_low = m.message.lower()
            wants_min = any(w in q_low for w in ["kam", "km", "chhot", "chot", "lowest", "minimum", "min "])
            filtered = {k: v for k, v in result["peaks"].items()
                        if (wants_min and k.startswith("min_")) or (not wants_min and k.startswith("max_"))}
            label = "SABSE KAM (min)" if wants_min else "SABSE ZYADA (max)"
            rank_block += f"\n\n{label} VALUES (server ne calculate kiya — WAHI batao):\n{json.dumps(filtered, default=str)}\n"
        
        reply = await _ask(ANSWER_PROMPT,
            f"Sawaal: {m.message}\n\n"
            f"Total entries mili: {result['count']}\n"
            f"Filter laga: {json.dumps(result.get('filter_used', {}), default=str)}\n\n"
            f"NUMERIC TOTALS (server ne calculate kiye — 100% sahi, inhe use karo):\n"
            f"{json.dumps(result.get('summary', {}), default=str)}"
            f"{rank_block}"
            f"{combined_info}\n"
            f"Sample rows (pehli 15, reference ke liye):\n"
            f"{json.dumps(result.get('rows', [])[:15], default=str)[:4000]}",
            4000, 0.3)
        if not reply:
            reply = f"✅ {result['count']} entries mili ({result['collection']})."
    except Exception:
        reply = f"✅ {result['count']} entries mili."

    return {"reply": reply, "data": result}


@app.get("/", response_class=HTMLResponse)
async def home():
    with open("ai/chatbot/static/index.html") as f:
        return f.read()


app.mount("/static", StaticFiles(directory="ai/chatbot/static"), name="static")