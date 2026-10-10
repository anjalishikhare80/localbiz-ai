# Celery is optional: the app works without it (tasks can also be run via management commands).
try:
    from .celery import app as celery_app  # noqa: F401

    __all__ = ("celery_app",)
except ImportError:  # celery not installed
    pass
