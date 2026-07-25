FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps needed to build psycopg2 against Postgres
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[django,dev]"

# Copy source
COPY . .

EXPOSE 8000

CMD ["python", "demo_project/manage.py", "runserver", "0.0.0.0:8000"]