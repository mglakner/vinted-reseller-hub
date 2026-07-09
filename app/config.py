import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "vintedhub.db"
MEDIA_DIR = DATA_DIR / "media"

# Login password for the whole app (this is the entire access control — pick a good one).
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secret")

# Gmail (sale-email watcher + weekly report). Use a Gmail app password (needs 2FA).
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Your Vinted marketplace host, e.g. www.vinted.co.uk, www.vinted.de, www.vinted.fr, www.vinted.com …
VINTED_DOMAIN = os.environ.get("VINTED_DOMAIN", "www.vinted.com")

# Image generation backend. "mcp" = Higgsfield hosted MCP (see app/higgsfield_mcp.py). "" = disabled.
HIGGSFIELD_BACKEND = os.environ.get("HIGGSFIELD_BACKEND", "")

# Watermark text drawn on generated shots 01–04 (e.g. your @handle). Empty = no watermark.
WATERMARK_TEXT = os.environ.get("WATERMARK_TEXT", "")

# Currency suffix shown after amounts, e.g. "kr", "€", "£", "$".
CURRENCY = os.environ.get("CURRENCY", "kr")

DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
