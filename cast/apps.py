from django.apps import AppConfig


class CastConfig(AppConfig):
    name: str = "cast"

    def ready(self) -> None:
        from .appsettings import init_cast_settings

        init_cast_settings()
