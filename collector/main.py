import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

KAFKA_SERVER = "localhost:9092"
TOPIC = "game-events"

producer: AIOKafkaProducer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_SERVER)
    await producer.start()
    print("✅ Kafka producer connected")
    yield
    await producer.stop()
    print("👋 Kafka producer stopped")


app = FastAPI(title="Event Collector", lifespan=lifespan)


class GameEvent(BaseModel):
    event_id: str
    event_type: str          # DEPOSIT, WITHDRAWAL, LOGIN, REWARD...
    user_id: str
    transaction_id: str | None = None
    amount: float | None = None
    service: str = "game"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = {}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/events", status_code=202)
async def collect_event(event: GameEvent):
    try:
        data = event.model_dump_json().encode("utf-8")
        # key=user_id => same user ke events same partition => order guaranteed
        await producer.send_and_wait(TOPIC, value=data, key=event.user_id.encode("utf-8"))
        return {"accepted": True, "event_id": event.event_id}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Kafka error: {e}")