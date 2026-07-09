# Deploying Vinted Hub

A small always-on machine is all you need — a Raspberry Pi 4 (or newer) is
plenty. These steps assume Docker.

## 1. Install and run

```sh
git clone https://github.com/MadsRudolph/vinted-reseller-hub.git
cd vinted-reseller-hub
cp .env.example .env
nano .env        # set APP_PASSWORD, SECRET_KEY, VINTED_DOMAIN, CURRENCY
docker compose up -d --build
```

The app is now on `http://<machine-ip>:8000`. Data (SQLite DB + photos) lives in
`./data`, which is bind-mounted so it survives rebuilds.

## 2. A public HTTPS URL (recommended)

To use the app — and install it on your phone — from anywhere, put it behind
HTTPS. Two easy options:

- **Cloudflare Tunnel** (no open ports, free; needs a domain on Cloudflare):
  ```sh
  cloudflared tunnel login
  cloudflared tunnel create vinted-hub
  cloudflared tunnel route dns vinted-hub vinted.yourdomain.com
  # ~/.cloudflared/config.yml:
  #   tunnel: <id>
  #   credentials-file: /path/<id>.json
  #   ingress:
  #     - hostname: vinted.yourdomain.com
  #       service: http://localhost:8000
  #     - service: http_status:404
  sudo cloudflared service install && sudo systemctl enable --now cloudflared
  ```
- **Reverse proxy** (Caddy/nginx/Traefik) terminating TLS in front of
  `http://localhost:8000`. If your proxy sets `X-Forwarded-Proto`, the app already
  honours it (uvicorn runs with `--proxy-headers`).

Then open the HTTPS URL in the phone browser and **Add to Home Screen** to install
it as an app.

## 3. Connect the integrations (all optional)

Open the **Status** page in the app.

**Higgsfield (AI product photos)** — run the one-time OAuth on any machine with a
browser, then point the app at it:
```sh
python -m app.higgsfield_mcp login      # opens a browser; log in to Higgsfield
```
This writes `data/higgsfield_tokens.json` (auto-refreshing). If you ran it on a
different machine than the server, copy that file into the server's `data/`.
Then set `HIGGSFIELD_BACKEND=mcp` in `.env` and recreate the container. Optionally
set `WATERMARK_TEXT=@yourhandle`.

**Vinted (stat sync + listing pre-fill)** — log in to Vinted in a browser, open
DevTools → Network, copy the whole `Cookie` request header from any
`vinted.*` request, and paste it on the Status page with your user ID
(`fetch('/api/v2/users/current').then(r=>r.json()).then(d=>console.log(d.user.id))`
in the browser console). The cookie expires periodically — re-paste it when the
Status page reports a sync error.

**Gmail (auto sale logging + weekly report)** — enable 2FA on the Google account,
create an app password at <https://myaccount.google.com/apppasswords>, and put
`GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` in `.env`. This must be the inbox that
receives your Vinted sale emails.

## 4. Assisted listing (one-time, on the computer you list from)

On the Status page you'll find two options:
- a **bookmarklet** you drag to your bookmarks bar (no install), or
- a **Tampermonkey userscript** for true one-click auto-fill (in Chrome you must
  enable `chrome://extensions` → Developer mode / "Allow User Scripts").

## 5. Backups

`scripts/backup.sh` snapshots the SQLite DB + photos to `./backups` (keeps 14
days). Add it to cron:
```sh
crontab -e
# 0 3 * * * /path/to/vinted-reseller-hub/scripts/backup.sh
```

## Updating

```sh
git pull
docker compose up -d --build
```
The database migrates itself on start.
