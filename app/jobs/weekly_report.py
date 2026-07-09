"""Weekly status email (Monday morning) via Gmail SMTP — reuses
GMAIL_ADDRESS/GMAIL_APP_PASSWORD from .env."""
import smtplib
from datetime import date, timedelta
from email.mime.text import MIMEText

from sqlmodel import select

from .. import config
from ..db import session_scope
from ..metrics import compute_dashboard
from ..models import Item

CUR = config.CURRENCY


def _money(v) -> str:
    return f"{v:,.0f}".replace(",", " ") + f" {CUR}"


def send() -> str:
    if not config.GMAIL_ADDRESS or not config.GMAIL_APP_PASSWORD:
        return "Skipped: Gmail not configured."

    week_ago = date.today() - timedelta(days=7)
    with session_scope() as session:
        d = compute_dashboard(session)
        sold_week = list(session.exec(
            select(Item).where(Item.status == "sold", Item.sale_date >= week_ago)
        ))
        new_week = [
            i for i in session.exec(select(Item))
            if i.purchase_date and i.purchase_date >= week_ago
        ]

        profit_week = sum(i.net_profit or 0 for i in sold_week)
        lines = [
            f"This week on Vinted ({week_ago:%d/%m}–{date.today():%d/%m})",
            "",
            f"Sold this week: {len(sold_week)} items, {_money(profit_week)} profit",
            *(f"  • {i.name} — {_money(i.net_profit or 0)}" for i in sold_week),
            "",
            f"New items bought: {len(new_week)}",
            f"Active listings: {d.total_active}",
            f"Tied up in stock: {_money(d.stock_value)}",
            f"Overall profit to date: {_money(d.overall_profit)}",
        ]
        if d.stale_items:
            lines += ["", f"Slow movers (30+ days, no offers): {len(d.stale_items)} — see the dashboard."]

    msg = MIMEText("\n".join(lines), "plain", "utf-8")
    msg["Subject"] = f"Vinted Hub weekly report: {_money(profit_week)} profit"
    msg["From"] = config.GMAIL_ADDRESS
    msg["To"] = config.GMAIL_ADDRESS

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        smtp.send_message(msg)
    return f"Report sent to {config.GMAIL_ADDRESS}."
