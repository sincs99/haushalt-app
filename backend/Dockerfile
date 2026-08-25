FROM python:3.12-slim

WORKDIR /app

# System-Dependencies für psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user für Production-Sicherheit
RUN useradd -r -s /bin/false app \
    && mkdir -p /app/data/uploads \
    && chown -R app:app /app
USER app

# --workers 1: python-socketio ohne Message-Queue kann nicht multi-worker laufen
# --proxy-headers: X-Forwarded-For wird zu request.client.host (für Rate-Limiting)
# --forwarded-allow-ips='*': Akzeptabel, da Port 8000 nie ausserhalb des Docker-Netzwerks exponiert ist
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
