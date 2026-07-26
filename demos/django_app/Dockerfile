FROM python:3.12-slim

ENV PYTHONTDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies needed for Postgres drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy packaging specs first to leverage Docker layer caching
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[django,dev]"

# Copy entire repository context
COPY . .

EXPOSE 8000

# Execute manage.py from its new isolated workspace path
CMD ["python", "demos/django/manage.py", "runserver", "0.0.0.0:8000"]