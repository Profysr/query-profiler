FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies needed for Postgres drivers and building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire repository context first so pyproject.toml, dqs/, and demos/ are all present
COPY . .

# Upgrade pip and install the package in editable mode with django and dev extras
RUN pip install --upgrade pip && pip install --no-cache-dir -e ".[django,dev]"

EXPOSE 8000

# Execute manage.py from its isolated workspace path
CMD ["python", "demos/drf/manage.py", "runserver", "0.0.0.0:8000"]