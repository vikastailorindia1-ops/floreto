import asyncio
import json
import uuid

import asyncpg
from aiokafka import AIOKafkaConsumer

from engine.telegram_alerts import send_alert
from engine.dw_rules import REAL_RULES
from ai.investigator import investigate, send_telegram

KAFKA_SERVER = "localhost:9092"
TOPIC = "game-events"
GROUP = "security-engine"
PG_DSN = "postgresql://floreto:floreto_dev_pass@localhost:5432/security"

pg: asyncpg.Pool | None = None

RULES = REAL_RULES   # ← sipahiyon ki list dw_rules.py se


async def save_incident(finding: dict, event: dict) -> str:
    code = f"INC-{uuid.uuid4().hex[:8].upper()}"
    await pg.execute(
        "INSERT INTO incidents (incident_code, rule, severity, message, event) VALUES ($1,$2,$3,$4,$5)",
        code, finding["rule"], finding["severity"], finding["message"], json.dumps(event),
    )
    return code


async def auto_investigate(code: str):
    try:
        print(f"🕵️ auto-jaanch shuru: {code} (background)")
        report = await investigate(code)
        await send_telegram(report)      # sirf YE ek message — poori report ke saath
        print(f"🕵️ report bheji: {code}")
    except Exception as e:
        print(f"⚠️ jaanch fail ({code}): {e}")


async def process_event(event: dict):
    for rule in RULES:
        finding = await rule(event)
        if finding:
            code = await save_incident(finding, event)
            print(f"🚨 {code} [{finding['severity']}] {finding['rule']}: {finding['message']}")
            if finding["severity"] == "CRITICAL":
                # CRITICAL: turant alarm NAHI — seedha jaanch, phir EK poori report
                asyncio.create_task(auto_investigate(code))
            else:
                # HIGH/MEDIUM: turant alarm (in par auto-jaanch nahi)
                await send_alert(code, finding)

async def main():
    global pg
    pg = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=5)
    print("📔 PostgreSQL diary connected")
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_SERVER,
        group_id=GROUP,
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    await consumer.start()
    print("💂 Security Engine on duty (REAL rules)...")
    try:
        async for msg in consumer:
            await process_event(msg.value)
    finally:
        await consumer.stop()
        await pg.close()


if __name__ == "__main__":
    asyncio.run(main())