# engine/alerts.py — phone pe turant khabar (Telegram)
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
PUSH_SEVERITIES = {"CRITICAL", "HIGH"}   # MEDIUM/LOW sirf diary me — phone shaant


async def send_alert(code: str, finding: dict) -> None:
    sev = finding.get("severity")
    if not BOT or not CHAT:
        print("⚠️ alert skip: token/chat_id nahi mile")
        return

    # severity ke hisaab se emoji + heading
    icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}.get(sev, "⚪")
    if sev not in ("CRITICAL", "HIGH", "MEDIUM"):
        return  # LOW sirf diary me

    text = (
        f"{icon} {sev}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚠️ Problem: {finding['rule'].replace('_', ' ').title()}\n\n"
        f"{finding['message']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔖 ID: {code}"
    )
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.post(f"https://api.telegram.org/bot{BOT}/sendMessage",
                                json={"chat_id": CHAT, "text": text})
            if resp.status_code != 200:
                print(f"⚠️ telegram bola: {resp.status_code} {resp.text[:120]}")
    except Exception as e:
        print(f"⚠️ alert fail: {e}")
    if not BOT or not CHAT or finding.get("severity") not in PUSH_SEVERITIES:
        return
    text = (
        f"🚨 {finding['severity']} — {finding['rule']}\n"
        f"{finding['message']}\n"
        f"Incident: {code}"
    )
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"https://api.telegram.org/bot{BOT}/sendMessage",
                         json={"chat_id": CHAT, "text": text})
    except Exception as e:
        print(f"⚠️ alert fail: {e}")   # alert gire to bhi engine kabhi na ruke