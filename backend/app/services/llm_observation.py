"""Optional in-memory HTTP observations, isolated by context and shared by worker threads."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallObservation:
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


_observers: ContextVar[tuple[CallObservation, ...]] = ContextVar("llm_observers", default=())


@contextmanager
def observe_calls():
    observation = CallObservation()
    token = _observers.set((*_observers.get(), observation))
    try:
        yield observation
    finally:
        _observers.reset(token)


def record_observation(**event: Any) -> None:
    for observation in _observers.get():
        with observation.lock:
            observation.events.append(dict(event))
