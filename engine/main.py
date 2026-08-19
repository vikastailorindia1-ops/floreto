import asyncio
import json
import uuid

import asyncpg
import redis.asyncio as redis
from aiokafka import AIOKafkaConsumer
from engine.invariants import INVARIANTS

KAFKA_SERVER = "localhost:9092"
TOPIC = "game-events"
GROUP = "security-engine"
PG_DSN = "postgresql://floreto:floreto_dev_pass@localhost:5432/security"

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
pg: asyncpg.Pool | None = None


async def rule_duplicate_transaction(event: dict) -> dict | None:
    txn = event.get("transaction_id")
    if not txn:
        return None
    # NX = sirf tab set karo agar key pehle se nahi hai (atomic, race-proof)
    first_time = await r.set(f"txn:{txn}", event["event_id"], nx=True, ex=86400)
    if not first_time:
        return {
            "rule": "DUPLICATE_TRANSACTION",
            "severity": "HIGH",
            "message": f"txn {txn} DOBARA aaya! user={event.get('user_id')} amount={event.get('amount')}",
        }
    return None


RULES = [rule_duplicate_transaction] + INVARIANTS

async def save_incident(finding: dict, event: dict) -> str:
    code = f"INC-{uuid.uuid4().hex[:8].upper()}"
    await pg.execute(
        "INSERT INTO incidents (incident_code, rule, severity, message, event) VALUES ($1,$2,$3,$4,$5)",
        code, finding["rule"], finding["severity"], finding["message"], json.dumps(event),
    )
    return code


async def process_event(event: dict):
    for rule in RULES:
        finding = await rule(event)
        if finding:
            code = await save_incident(finding, event)
            print(f"🚨 {code} [{finding['severity']}] {finding['rule']}: {finding['message']}")


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
    print("💂 Security Engine on duty...")
    try:
        async for msg in consumer:
            await process_event(msg.value)
    finally:
        await consumer.stop()
        await pg.close()


if __name__ == "__main__":
    asyncio.run(main())