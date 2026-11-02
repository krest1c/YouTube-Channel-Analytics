class AppError(Exception):
    """Базовая ошибка приложения: превращается в JSON {"error": {"code", "message"}}."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)

    default_message = "Внутренняя ошибка сервера"


class InvalidQueryError(AppError):
    status_code = 422
    code = "invalid_query"
    default_message = "Не удалось распознать канал. Введите название, @handle, ID (UC...) или ссылку на канал."


class ChannelNotFoundError(AppError):
    status_code = 404
    code = "channel_not_found"
    default_message = "Канал не найден"


class QuotaExceededError(AppError):
    status_code = 429
    code = "quota_exceeded"
    default_message = "Исчерпана квота YouTube API. Попробуйте позже."


class ConfigError(AppError):
    status_code = 500
    code = "config_error"
    default_message = "Сервер неверно настроен"


class YouTubeAPIError(AppError):
    status_code = 502
    code = "youtube_api_error"
    default_message = "Ошибка при обращении к YouTube API"

    def __init__(self, message: str | None = None, *, http_status: int | None = None, reason: str = ""):
        super().__init__(message)
        self.http_status = http_status
        self.reason = reason
