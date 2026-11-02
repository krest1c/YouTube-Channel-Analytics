"""Бизнес-логика: канал + ролики -> статистика для сайта."""
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

from app.core.cache import TTLCache
from app.schemas import ChannelInfo, ChannelStatsResponse, MonthlyPoint, VideoPoint
from app.services.youtube import ChannelRef, Video, YouTubeClient, parse_channel_query

TOP_VIDEOS_COUNT = 5


def _video_point(v: Video) -> VideoPoint:
    return VideoPoint(
        id=v.id,
        title=v.title,
        published_at=v.published_at,
        views=v.views,
        url=f"https://www.youtube.com/watch?v={v.id}",
    )


def build_monthly(videos: list[Video]) -> list[MonthlyPoint]:
    """Просмотры по месяцам выхода роликов. Пустые месяцы заполняются нулями,
    чтобы ось времени на графике была непрерывной."""
    if not videos:
        return []

    buckets: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])  # [роликов, просмотров]
    for v in videos:
        b = buckets[(v.published_at.year, v.published_at.month)]
        b[0] += 1
        b[1] += v.views

    first, last = min(buckets), max(buckets)
    result: list[MonthlyPoint] = []
    year, month = first
    while (year, month) <= last:
        count, views = buckets.get((year, month), (0, 0))
        result.append(MonthlyPoint(period=f"{year:04d}-{month:02d}", videos=count, views=views))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return result


def build_stats(channel: dict, videos: list[Video], max_videos: int) -> ChannelStatsResponse:
    snippet = channel.get("snippet", {})
    ch_stats = channel.get("statistics", {})

    videos_sorted = sorted(videos, key=lambda v: v.published_at)
    views_list = [v.views for v in videos_sorted]
    analyzed_views = sum(views_list)
    count = len(views_list)

    video_count = int(ch_stats.get("videoCount", count))
    hidden_subs = ch_stats.get("hiddenSubscriberCount", False)
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")

    info = ChannelInfo(
        id=channel["id"],
        title=snippet.get("title", ""),
        handle=snippet.get("customUrl"),
        url=f"https://www.youtube.com/channel/{channel['id']}",
        thumbnail_url=thumb,
        subscriber_count=None if hidden_subs or "subscriberCount" not in ch_stats else int(ch_stats["subscriberCount"]),
        video_count=video_count,
    )

    return ChannelStatsResponse(
        channel=info,
        total_views=int(ch_stats.get("viewCount", analyzed_views)),
        average_views_per_video=round(analyzed_views / count, 2) if count else 0.0,
        median_views_per_video=float(median(views_list)) if count else 0.0,
        analyzed_videos=count,
        analyzed_videos_views=analyzed_views,
        truncated=count >= max_videos and video_count > count,
        top_videos=[_video_point(v) for v in sorted(videos, key=lambda v: v.views, reverse=True)[:TOP_VIDEOS_COUNT]],
        timeline=[_video_point(v) for v in videos_sorted],
        monthly=build_monthly(videos_sorted),
        generated_at=datetime.now(timezone.utc),
    )


class StatsService:
    def __init__(self, client: YouTubeClient, cache: TTLCache, max_videos: int):
        self._yt = client
        self._cache = cache
        self._max_videos = max_videos

    async def get_channel_stats(self, query: str) -> ChannelStatsResponse:
        ref = parse_channel_query(query)
        return await self._cache.get_or_set(ref.cache_key, lambda: self._compute(ref))

    async def _compute(self, ref: ChannelRef) -> ChannelStatsResponse:
        channel = await self._yt.resolve_channel(ref)
        uploads_id = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        video_ids = await self._yt.get_upload_video_ids(uploads_id, limit=self._max_videos)
        videos = await self._yt.get_videos(video_ids) if video_ids else []
        return build_stats(channel, videos, self._max_videos)
