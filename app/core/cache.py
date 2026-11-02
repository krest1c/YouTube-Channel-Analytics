import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable


class TTLCache:
    """Простой in-memory кэш с TTL и защитой от «толпы» одинаковых запросов.

    Если 10 пользователей одновременно запросят один и тот же канал,
    в YouTube API уйдёт только один набор запросов.
    """

    def __init__(self, ttl_seconds: int, maxsize: int = 512):
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.monotonic() + self._ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        if self._ttl <= 0:
            return await factory()

        hit = self.get(key)
        if hit is not None:
            return hit

        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                hit = self.get(key)
                if hit is not None:
                    return hit
                value = await factory()
                self.set(key, value)
                return value
        finally:
            self._locks.pop(key, None)
