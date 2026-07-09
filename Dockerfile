FROM python:3.12-slim

# Node til Higgsfield CLI (billede-generering)
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @higgsfield/cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/vinted-hub
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV DATA_DIR=/srv/vinted-hub/data
EXPOSE 8000
# --proxy-headers/--forwarded-allow-ips: respekter X-Forwarded-Proto/Host fra
# cloudflared, så genererede URL'er bliver https (ikke http).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
