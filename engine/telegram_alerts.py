# engine/alerts.py — phone pe turant khabar (Telegram)
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
PUSH_SEVERITIES = {"CRITICAL", "HIGH"}   # MEDIUM/LOW sirf diary me — phone shaant


async def send_alert(code: str, finding: dict) -> None:
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