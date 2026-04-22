FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl нужен для healthcheck в docker-compose
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Сначала только манифест — слой деп-установки кешируется, пока pyproject не меняется
COPY pyproject.toml ./

# app/ нужен для hatchling (package discovery)
COPY app ./app

RUN pip install --upgrade pip \
    && pip install .

# Остальное — меняется чаще, ниже в слоях
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

# Миграции перед стартом. APScheduler требует --workers 1 (иначе дубли заявок).
CMD alembic upgrade head \
    && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
