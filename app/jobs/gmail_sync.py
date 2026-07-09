"""Watches Gmail (IMAP) for Vinted "your item sold" emails and marks the
matching item as sold.

Requires GMAIL_ADDRESS + GMAIL_APP_PASSWORD in .env (an app password, needs 2FA).
Uses IMAP rather than the Gmail API, so there's no Google Cloud project to set up.
"""
import email
import email.header
import imaplib
import re
from datetime import date
from difflib import SequenceMatcher

from sqlmodel import select

from .. import config
from ..db import get_setting, session_scope, set_setting
from ..models import Item

SOLD_SUBJECT_RE = re.compile(r"(dit salg|solgt|er blevet solgt|sold)", re.IGNORECASE)
PRICE_RE = re.compile(r"(\d+(?:[.,]\d{2})?)\s*kr", re.IGNORECASE)


def _decode(value: str) -> str:
    parts = email.header.decode_header(value or "")
    return "".join(
        p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, enc in parts
    )


def _body_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""


def _match_item(session, title: str) -> Item | None:
    """Fuzzy-match mailens varenavn mod aktive varer."""
    candidates = list(session.exec(select(Item).where(Item.status.in_(("active", "offer")))))
    best, best_score = None, 0.0
    for item in candidates:
        score = SequenceMatcher(None, title.lower(), item.name.lower()).ratio()
        if score > best_score:
            best, best_score = item, score
    return best if best_score >= 0.6 else None


def sync() -> str:
    if not config.GMAIL_ADDRESS or not config.GMAIL_APP_PASSWORD:
        return "Skipped: Gmail not configured."

    with session_scope() as session:
        last_uid = int(get_setting(session, "gmail_last_uid", "0"))

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
    try:
        mail.select("INBOX", readonly=True)
        _, data = mail.uid("search", None, '(FROM "vinted")')
        uids = [int(u) for u in data[0].split()] if data and data[0] else []
        new_uids = [u for u in uids if u > last_uid]
        handled = 0

        for uid in new_uids:
            _, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode(msg.get("Subject", ""))
            if not SOLD_SUBJECT_RE.search(subject):
                continue
            body = _body_text(msg)
            price_match = PRICE_RE.search(body) or PRICE_RE.search(subject)
            price = float(price_match.group(1).replace(",", ".")) if price_match else None

            # Vinteds emne indeholder typisk varens titel i citationstegn
            title_match = re.search(r"[\"“”']([^\"“”']{4,})[\"“”']", subject + " " + body[:500])
            title = title_match.group(1) if title_match else subject

            with session_scope() as session:
                item = _match_item(session, title)
                if item:
                    item.status = "sold"
                    item.sale_date = date.today()
                    if price is not None:
                        item.sale_price = price
                    else:
                        item.needs_review = True
                        item.review_note = "Sold per the email, but the price couldn't be read."
                    session.add(item)
                else:
                    # no confident match — add a review item
                    session.add(Item(
                        name=f"(from email) {title[:80]}",
                        status="sold",
                        sale_price=price,
                        sale_date=date.today(),
                        needs_review=True,
                        review_note="Sale email couldn't be matched to an item — merge manually.",
                    ))
                session.commit()
            handled += 1

        with session_scope() as session:
            if uids:
                set_setting(session, "gmail_last_uid", str(max(uids)))
        return f"Tjekket {len(new_uids)} nye mails, behandlede {handled} salgsmails."
    finally:
        mail.logout()
