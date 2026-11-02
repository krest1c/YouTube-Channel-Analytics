"""Тонкий async-клиент YouTube Data API v3.

Расход квоты (лимит по умолчанию 10 000 единиц в сутки):
  channels.list      = 1
  playlistItems.list = 1  (на 50 роликов)
  videos.list        = 1  (на 50 роликов)
  search.list        = 100 (используем только как запасной вариант для поиска по названию)
"""
import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.core.exceptions import (
    ChannelNotFoundError,
    ConfigError,
    InvalidQueryError,
    QuotaExceededError,
    YouTubeAPIError,
)

API_BASE = "https://www.googleapis.com/youtube/v3"
PAGE_SIZE = 50
MAX_PARALLEL_REQUESTS = 5
MAX_RETRIES = 2

QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
CONFIG_REASONS = {"keyInvalid", "accessNotConfigured", "ipRefererBlocked", "forbidden"}

CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")


# --------------------------------------------------------------------------- #
# Разбор пользовательского ввода
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ChannelRef:
    kind: Literal["id", "handle", "username", "search"]
    value: str

    @property
    def cache_key(self) -> str:
        return f"{self.kind}:{self.value.lower()}"


def parse_channel_query(raw: str) -> ChannelRef:
    """Понимает: UC-id, @handle, ссылки (/channel/, /@, /user/, /c/) и просто название."""
    q = raw.strip()
    if not q:
        raise InvalidQueryError()

    if CHANNEL_ID_RE.match(q):
        return ChannelRef("id", q)

    if q.startswith("@"):
        handle = q[1:].strip()
        if not handle:
            raise InvalidQueryError()
        return ChannelRef("handle", handle)

    if "youtube.com" in q or "youtu.be" in q:
        url = q if "://" in q else f"https://{q}"
        parts = [p for p in urlparse(url).path.split("/") if p]
        if parts:
            head = parts[0]
            if head.startswith("@") and len(head) > 1:
                return ChannelRef("handle", head[1:])
            if len(parts) > 1 and head == "channel":
                return ChannelRef("id", parts[1])
            if len(parts) > 1 and head == "user":
                return ChannelRef("username", parts[1])
            if len(parts) > 1 and head == "c":
                return ChannelRef("search", parts[1])
        raise InvalidQueryError("Нужна ссылка именно на канал, а не на ролик или плейлист.")

    return ChannelRef("search", q)


# --------------------------------------------------------------------------- #
# Модель ролика
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Video:
    id: str
    title: str
    published_at: datetime
    views: int


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# Клиент
# --------------------------------------------------------------------------- #
class YouTubeClient:
    def __init__(self, api_key: str, http: httpx.AsyncClient):
        self._key = api_key
        self._http = http
        self._sem = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

    async def _get(self, endpoint: str, **params: Any) -> dict:
        if not self._key or self._key == "your_key_here":
            raise ConfigError("На сервере не задан YOUTUBE_API_KEY (см. .env.example)")

        params["key"] = self._key
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with self._sem:
                    resp = await self._http.get(f"{API_BASE}/{endpoint}", params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if resp.status_code == 200:
                return resp.json()

            self._raise_for_error(resp)

        raise YouTubeAPIError(f"Не удалось связаться с YouTube API: {last_error}")

    @staticmethod
    def _raise_for_error(resp: httpx.Response) -> None:
        try:
            err = resp.json().get("error", {})
        except ValueError:
            err = {}
        reason = ((err.get("errors") or [{}])[0]).get("reason", "")
        message = err.get("message") or resp.text[:200]

        if reason in QUOTA_REASONS:
            raise QuotaExceededError()
        if reason in CONFIG_REASONS or "API key" in message:
            raise ConfigError(f"Проблема с ключом YouTube API: {message}")
        raise YouTubeAPIError(message, http_status=resp.status_code, reason=reason)

    # ----------------------------- канал ----------------------------------- #
    async def _channels(self, **lookup: str) -> dict | None:
        data = await self._get(
            "channels",
            part="snippet,statistics,contentDetails",
            maxResults=1,
            **lookup,
        )
        items = data.get("items") or []
        return items[0] if items else None

    async def resolve_channel(self, ref: ChannelRef) -> dict:
        channel: dict | None = None

        if ref.kind == "id":
            channel = await self._channels(id=ref.value)
        elif ref.kind == "handle":
            channel = await self._channels(forHandle=f"@{ref.value}")
        elif ref.kind == "username":
            channel = await self._channels(forUsername=ref.value)
        else:  # search: обычное название
            # Дёшево (1 ед.): вдруг название совпадает с @handle
            if " " not in ref.value:
                channel = await self._channels(forHandle=f"@{ref.value}")
            # Дорого (100 ед.): полноценный поиск по названию
            if channel is None:
                found = await self._get(
                    "search", part="snippet", type="channel", q=ref.value, maxResults=1
                )
                items = found.get("items") or []
                if items:
                    channel = await self._channels(id=items[0]["snippet"]["channelId"])

        if channel is None:
            raise ChannelNotFoundError(f"Канал «{ref.value}» не найден")
        return channel

    # ----------------------------- ролики ---------------------------------- #
    async def get_upload_video_ids(self, uploads_playlist_id: str, limit: int) -> list[str]:
        """ID роликов канала от новых к старым, не больше `limit`."""
        ids: list[str] = []
        page_token: str | None = None

        while len(ids) < limit:
            params: dict[str, Any] = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                data = await self._get("playlistItems", **params)
            except YouTubeAPIError as exc:
                if exc.reason == "playlistNotFound":  # у канала нет загрузок
                    return []
                raise

            ids.extend(item["contentDetails"]["videoId"] for item in data.get("items", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return ids[:limit]

    async def get_videos(self, video_ids: list[str]) -> list[Video]:
        chunks = [video_ids[i : i + PAGE_SIZE] for i in range(0, len(video_ids), PAGE_SIZE)]
        responses = await asyncio.gather(
            *(
                self._get("videos", part="snippet,statistics", id=",".join(chunk), maxResults=PAGE_SIZE)
                for chunk in chunks
            )
        )

        videos: list[Video] = []
        for data in responses:
            for item in data.get("items", []):
                stats = item.get("statistics", {})
                videos.append(
                    Video(
                        id=item["id"],
                        title=item["snippet"]["title"],
                        published_at=_parse_dt(item["snippet"]["publishedAt"]),
                        views=int(stats.get("viewCount", 0)),  # у части роликов счётчик скрыт
                    )
                )
        return videos
