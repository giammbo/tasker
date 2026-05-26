# Dockerfile di Tasker v0.2.0.
# Differenze rispetto alla v0.1.0: dipendenze (Flask + SQLAlchemy + psycopg2)

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    APP_VERSION=0.2.0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN useradd --create-home --shell /bin/bash tasker && \
    chown -R tasker:tasker /app
USER tasker

EXPOSE 5000

CMD ["python", "app.py"]
