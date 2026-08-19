import asyncio
import json

import redis.asyncio as redis
from aiokafka import AIOKafkaConsumer

KAFKA_SERVER = "localhost:9092"
TOPIC = "game-events"
GROUP = "security-engine"

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


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


RULES = [rule_duplicate_transaction]


async def process_event(event: dict):
    for rule in RULES:
        finding = await rule(event)
        if finding:
            print(f"🚨 INCIDENT [{finding['severity']}] {finding['rule']}: {finding['message']}")


async def main():
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


if __name__ == "__main__":
    asyncio.run(main())