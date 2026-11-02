from datetime import datetime

from pydantic import BaseModel


class ChannelInfo(BaseModel):
    id: str
    title: str
    handle: str | None = None
    url: str
    thumbnail_url: str | None = None
    subscriber_count: int | None = None  # None, если автор скрыл число подписчиков
    video_count: int


class VideoPoint(BaseModel):
    id: str
    title: str
    published_at: datetime
    views: int
    url: str


class MonthlyPoint(BaseModel):
    period: str  # "YYYY-MM"
    videos: int  # сколько роликов вышло в этом месяце
    views: int  # сумма текущих просмотров этих роликов


class ChannelStatsResponse(BaseModel):
    channel: ChannelInfo

    # 1. Общее число просмотров канала за всё время (как показывает YouTube)
    total_views: int
    # 2. Среднее число просмотров на ролик (по проанализированным роликам)
    average_views_per_video: float
    median_views_per_video: float

    analyzed_videos: int
    analyzed_videos_views: int
    truncated: bool  # True, если роликов больше MAX_VIDEOS и анализ неполный

    top_videos: list[VideoPoint]

    # 3. Данные для графика
    timeline: list[VideoPoint]  # каждый ролик: дата выхода → просмотры (от старых к новым)
    monthly: list[MonthlyPoint]  # агрегат по месяцам, без пропусков

    generated_at: datetime
