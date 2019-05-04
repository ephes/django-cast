# -*- coding: utf-8
from django.apps import AppConfig
from watson import search as watson


class CastConfig(AppConfig):
    name = "cast"

    def ready(self):
        Post = self.get_model("Post")
        watson.register(Post)
