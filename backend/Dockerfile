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
# --forwarded-allow-ips: NICHT '*' — damit würde uvicorn den *linkesten*,
#   client-kontrollierten XFF-Eintrag übernehmen (Rate-Limit-Bypass).
#   Mit einer Liste vertrauenswürdiger Netze nimmt uvicorn den rechtesten
#   nicht-vertrauenswürdigen Hop.  Das Frontend-Nginx sendet ohnehin nur eine
#   einzige IP (siehe frontend/nginx.conf); dies ist Defense-in-Depth.
#   tests/test_rate_limit_proxy.py liest diesen Wert aus dieser Datei.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7'"]
