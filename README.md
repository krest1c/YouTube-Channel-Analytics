<img width="1536" height="1024" alt="Minimalist GitHub Banner for YouTube API" src="https://github.com/user-attachments/assets/aa784f73-962b-4fcb-9641-21ddcc40a3f6" />


# YouTube Channel Stats — backend

FastAPI-сервис: по названию / @handle / ссылке на YouTube-канал отдаёт статистику просмотров.

## Запуск

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # впишите YOUTUBE_API_KEY
uvicorn main:app --reload
```

Документация (Swagger): http://localhost:8000/docs

## API

`GET /api/channel/stats?query=<что угодно>` — `query` может быть:
`@MrBeast`, `https://www.youtube.com/@MrBeast`, `youtube.com/channel/UC...`, ID `UC...`, или просто название.

Ответ (сокращённо):

```json
{
  "channel": {"id": "UC...", "title": "...", "handle": "@...", "thumbnail_url": "...", "subscriber_count": 123, "video_count": 456},
  "total_views": 1000000,
  "average_views_per_video": 2500.5,
  "median_views_per_video": 1200.0,
  "analyzed_videos": 400,
  "truncated": false,
  "top_videos": [{"id": "...", "title": "...", "published_at": "...", "views": 1, "url": "..."}],
  "timeline": [{"published_at": "2024-01-10T00:00:00Z", "views": 100, "...": "..."}],
  "monthly": [{"period": "2024-01", "videos": 2, "views": 400}]
}
```

- `total_views` — общее число просмотров канала за всё время (как на странице канала).
- `average_views_per_video` — сумма просмотров роликов / число роликов.
- `timeline` — точки «дата выхода → просмотры» для каждого ролика (для scatter/line-графика).
- `monthly` — то же, сгруппированное по месяцам, без пропусков (для bar/area-графика).
- `truncated: true` — роликов больше `MAX_VIDEOS`, учтены самые новые.

Ошибки: `{"error": {"code": "...", "message": "..."}}` — 404 канал не найден, 422 непонятный ввод,
429 исчерпана квота, 500 неверный ключ, 502 сбой YouTube.

## Квота YouTube API (10 000 ед./сутки по умолчанию)

Канал на 2000 роликов ≈ 1 + 40 + 40 = 81 ед. Поиск по обычному названию (не @handle) стоит +100 ед.,
поэтому результаты кэшируются на `CACHE_TTL_SECONDS`.

## Структура

```
main.py                 # приложение, CORS, обработка ошибок
app/
  api/                  # роуты и зависимости
  core/                 # конфиг, исключения, TTL-кэш
  schemas/              # pydantic-модели ответа
  services/
    youtube.py          # клиент YouTube Data API v3
    stats.py            # подсчёт метрик и группировка по месяцам
tests/                  # тесты на моках, ключ не нужен
```

## Тесты

```bash
pip install pytest && pytest -q
```
