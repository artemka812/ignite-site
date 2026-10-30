"""Автономные тесты. Основной settings.py всегда использует PostgreSQL."""
from .settings import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
