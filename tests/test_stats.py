"""Проверка логики без реального YouTube API: подменяем сеть через httpx.MockTransport."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_stats_service
from app.core.cache import TTLCache
from app.core.exceptions import ChannelNotFoundError, InvalidQueryError
from app.services.stats import StatsService
from app.services.youtube import YouTubeClient, parse_channel_query

CHANNEL = {
    "id": "UC" + "a" * 22,
    "snippet": {"title": "Test", "customUrl": "@test", "thumbnails": {"default": {"url": "http://img"}}},
    "statistics": {"viewCount": "1000", "subscriberCount": "5", "videoCount": "3"},
    "contentDetails": {"relatedPlaylists": {"uploads": "UU_uploads"}},
}
VIDEOS = {
    "v1": ("2024-01-10T00:00:00Z", "100"),
    "v2": ("2024-01-20T00:00:00Z", "300"),
    "v3": ("2024-04-05T00:00:00Z", "200"),
}


def handler(request: httpx.Request) -> httpx.Response:
    path, q = request.url.path, request.url.params
    if path.endswith("/channels"):
        if q.get("forHandle") == "@missing":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json={"items": [CHANNEL]})
    if path.endswith("/playlistItems"):
        return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": v}} for v in VIDEOS]})
    if path.endswith("/videos"):
        items = [
            {"id": v, "snippet": {"title": v, "publishedAt": d}, "statistics": {"viewCount": c}}
            for v, (d, c) in VIDEOS.items()
            if v in q["id"].split(",")
        ]
        return httpx.Response(200, json={"items": items})
    if path.endswith("/search"):
        return httpx.Response(200, json={"items": []})
    return httpx.Response(404)


def make_service() -> StatsService:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return StatsService(YouTubeClient("test-key", http), TTLCache(60), max_videos=2000)


def test_parse_query():
    assert parse_channel_query("@MrBeast").kind == "handle"
    assert parse_channel_query("https://www.youtube.com/@MrBeast/videos").value == "MrBeast"
    assert parse_channel_query("youtube.com/channel/UC" + "a" * 22).kind == "id"
    assert parse_channel_query("UC" + "a" * 22).kind == "id"
    assert parse_channel_query("some channel name").kind == "search"
    with pytest.raises(InvalidQueryError):
        parse_channel_query("https://www.youtube.com/watch?v=abc")
    with pytest.raises(InvalidQueryError):
        parse_channel_query("   ")


def test_stats_math():
    result = asyncio.run(make_service().get_channel_stats("@test"))
    assert result.total_views == 1000
    assert result.analyzed_videos == 3
    assert result.average_views_per_video == 200.0
    assert result.median_views_per_video == 200.0
    assert result.truncated is False
    assert [v.id for v in result.timeline] == ["v1", "v2", "v3"]
    assert result.top_videos[0].id == "v2"
    # янв, фев (0), мар (0), апр — пустые месяцы заполнены
    assert [(m.period, m.videos, m.views) for m in result.monthly] == [
        ("2024-01", 2, 400),
        ("2024-02", 0, 0),
        ("2024-03", 0, 0),
        ("2024-04", 1, 200),
    ]


def test_channel_not_found():
    with pytest.raises(ChannelNotFoundError):
        asyncio.run(make_service().get_channel_stats("@missing"))


def test_http_layer():
    from main import app

    service = make_service()
    app.dependency_overrides[get_stats_service] = lambda: service
    client = TestClient(app)

    ok = client.get("/api/channel/stats", params={"query": "@test"})
    assert ok.status_code == 200 and ok.json()["average_views_per_video"] == 200.0

    nf = client.get("/api/channel/stats", params={"query": "@missing"})
    assert nf.status_code == 404 and nf.json()["error"]["code"] == "channel_not_found"

    bad = client.get("/api/channel/stats", params={"query": "https://youtube.com/watch?v=1"})
    assert bad.status_code == 422

    assert client.get("/api/health").json() == {"status": "ok"}
    app.dependency_overrides.clear()
