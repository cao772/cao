"""Bounded process-local cache for immutable, versioned project search evidence."""
from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from time import monotonic
from typing import Any, Callable


class MaterialSearchCache:
    def __init__(self, capacity: int = 32, ttl: float = 30.0, clock: Callable[[], float] = monotonic):
        self.capacity = capacity
        self.ttl = ttl
        self.clock = clock
        self.entries: OrderedDict[tuple[str, str], tuple[Any, float, dict]] = OrderedDict()
        self.lock = RLock()

    def get(self, database: str, project: str, revision: Any, build: Callable[[], dict]) -> dict:
        key = (database, project)
        with self.lock:
            cached = self.entries.get(key)
            if cached and cached[0] == revision and self.clock() - cached[1] < self.ttl:
                self.entries.move_to_end(key)
                return cached[2]
            # Failed builds never enter the cache; the next request can retry.
            value = build()
            self.entries[key] = (revision, self.clock(), value)
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
            return value


material_search_cache = MaterialSearchCache()
