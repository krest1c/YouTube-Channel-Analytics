import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.routes import router
from app.core.cache import TTLCache
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.youtube import YouTubeClient

logger = logging.getLogger("yt-stats")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.youtube_api_key or settings.youtube_api_key == "your_key_here":
        logger.warning("YOUTUBE_API_KEY не задан — запросы к API будут возвращать ошибку конфигурации")

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as http:
        app.state.youtube = YouTubeClient(settings.youtube_api_key, http)
        app.state.cache = TTLCache(settings.cache_ttl_seconds)
        yield


app = FastAPI(title="YouTube Channel Stats", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


app.include_router(router)

INDEX_HTML = Path(__file__).parent / "index.html"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(INDEX_HTML)

# Запуск: uvicorn main:app --reload
