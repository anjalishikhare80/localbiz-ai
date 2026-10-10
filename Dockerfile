FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
# collectstatic needs settings to import, but not a real database or secret
RUN SECRET_KEY=build-only DB_NAME=x DB_USER=x DB_PASSWORD=x python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
