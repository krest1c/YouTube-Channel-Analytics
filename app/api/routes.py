from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_stats_service
from app.schemas import ChannelStatsResponse
from app.services.stats import StatsService

router = APIRouter(prefix="/api")


@router.get("/health", tags=["service"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/channel/stats", response_model=ChannelStatsResponse, tags=["channel"])
async def channel_stats(
    query: str = Query(
        ...,
        min_length=1,
        max_length=200,
        description="Название канала, @handle, ID (UC...) или ссылка на канал",
        examples=["@MrBeast", "https://www.youtube.com/@MrBeast"],
    ),
    service: StatsService = Depends(get_stats_service),
) -> ChannelStatsResponse:
    return await service.get_channel_stats(query)
