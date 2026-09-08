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

    # har rule ka aasaan-bhasha naam + kya karna hai
    RULE_INFO = {
        "DUPLICATE_UTR":            ("Ek UTR do baar use hua", "Duplicate deposit — turant check karo"),
        "UTR_STOLEN":               ("Kisi aur ka UTR chori", "User ne doosre ka UTR laga diya"),
        "UTR_REUSED_AT_REQUEST":    ("Purana UTR dobara", "Same UTR se nayi request bani"),
        "DOUBLE_APPROVAL":          ("Ek transaction 2 baar approve", "Paisa do baar gaya — turant roko"),
        "APPROVAL_WITHOUT_REQUEST": ("Bina request ke approve", "Request event nahi tha, phir bhi paisa add hua"),
        "AMOUNT_CHANGED_AT_APPROVAL": ("Amount beech me badal gaya", "Request kuch, approve kuch aur"),
        "BONUS_ABOVE_HARD_CAP":     ("Bonus limit se zyada", "Cap bypass — bonus galat"),
        "NEGATIVE_CLOSING":         ("Balance negative ho gaya", "Kisi ka balance minus me — bug"),
        "BAD_AMOUNT":               ("Amount galat (0 ya minus)", "Fake/tampered amount"),
        "USER_NOT_IN_DB":           ("User DB me hai hi nahi", "Fake event — API se banaya laga"),
        "AGENT_NOT_IN_DB":          ("Agent DB me hai hi nahi", "Fake event — forged"),
        "WRONG_AGENT_FOR_USER":     ("Galat agent ne approve kiya", "Hierarchy bypass — apne user ka nahi"),
        "UNKNOWN_EVENT_TYPE":       ("Anjaan event aaya", "Flow ke bahar ka event — chhed-chhaad"),
        "MALFORMED_TXN_ID":         ("Transaction ID format galat", "API se banaya fake laga"),
        "MALFORMED_USER_ID":        ("User ID format galat", "Fake event"),
        "MALFORMED_AGENT_ID":       ("Agent ID missing/galat", "Emitter ka shape nahi — tampered"),
        "MALFORMED_FIELD":          ("Field ka data galat", "Type mismatch — tampered"),
        "STEP_REPEATED":            ("Ek step do baar chala", "Retry/duplicate money-move"),
        "STEP_OUT_OF_ORDER":        ("Steps galat order me", "Flow toota — beech ka step pehle"),
        "STEPS_MISSING_AT_FINAL":   ("Kuch steps skip huye", "Adhoora flow — chhupa path"),
        "UNKNOWN_STEP":             ("Anjaan step aaya", "Flow ke bahar"),
    }
    rule = finding.get("rule", "?")
    nice_name, action = RULE_INFO.get(rule, (rule.replace("_", " ").title(), "Manual review karo"))

    text = (
        f"{icon} {sev} ALERT\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚠️ {nice_name}\n\n"
        f"📝 {finding['message']}\n\n"
        f"👉 {action}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔖 {code}  •  ⏰ {__import__('datetime').datetime.now().strftime('%d-%b %H:%M')}"
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