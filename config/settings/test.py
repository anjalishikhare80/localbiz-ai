"""
Fast settings for running the test-suite WITHOUT PostgreSQL (uses SQLite in memory).

    python manage.py test --settings=config.settings.test

Run the suite with the normal dev settings (PostgreSQL) before deploying:
    python manage.py test
"""
import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DB_NAME", "x")
os.environ.setdefault("DB_USER", "x")
os.environ.setdefault("DB_PASSWORD", "x")

from .base import *  # noqa: F401,F403,E402

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"anon": "10000/hour", "user": "10000/hour", "login": "10000/min"}}  # noqa: F405
MEDIA_ROOT = BASE_DIR / "media_test"  # noqa: F405
ML_ARTIFACT_DIR = BASE_DIR / "ml_artifacts_test"  # noqa: F405
