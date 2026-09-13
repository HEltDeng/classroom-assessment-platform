from __future__ import annotations

import asyncio
import json
import queue
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass(eq=False)
class Subscriber:
    events: queue.Queue[dict] = field(default_factory=queue.Queue)


class SessionEventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[Subscriber]] = {}

    def subscribe(self, session_id: str) -> Subscriber:
        subscriber = Subscriber()
        self._subscribers.setdefault(session_id, set()).add(subscriber)
        return subscriber

    def unsubscribe(self, session_id: str, subscriber: Subscriber) -> None:
        subscribers = self._subscribers.get(session_id)
        if not subscribers:
            return
        subscribers.discard(subscriber)
        if not subscribers:
            self._subscribers.pop(session_id, None)

    def publish(self, session_id: str, event: dict) -> None:
        for subscriber in list(self._subscribers.get(session_id, set())):
            subscriber.events.put(event)

    async def stream(self, session_id: str, subscriber: Subscriber) -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.events.get, True, 15)
                    yield f"event: session.update\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            self.unsubscribe(session_id, subscriber)


event_broker = SessionEventBroker()
