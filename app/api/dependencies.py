from fastapi import Request

from app.core.config import get_settings
from app.services.stats import StatsService


def get_stats_service(request: Request) -> StatsService:
    return StatsService(
        client=request.app.state.youtube,
        cache=request.app.state.cache,
        max_videos=get_settings().max_videos,
    )
