from django.apps import AppConfig

from .appsettings import init_cast_settings


class CastConfig(AppConfig):
    name: str = "cast"

    def ready(self) -> None:
        init_cast_settings()
