"""Henter views/likes/bud/status for aktive annoncer fra Vinteds interne API.

Requires a session cookie set on the /status page. The cookie expires
periodically; the job reports an error on /status when it needs refreshing.

Run gently (twice a day) — Vinted uses DataDome bot protection, and frequent
polling risks getting the account limited.
"""
import json
from difflib import SequenceMatcher

import httpx
from sqlmodel import select

from .. import config
from ..db import get_setting, session_scope
from ..models import Item, ItemImage

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _client(cookie: str) -> httpx.Client:
    return httpx.Client(
        base_url=f"https://{config.VINTED_DOMAIN}",
        headers={"User-Agent": UA, "Accept": "application/json", "Cookie": cookie},
        timeout=30,
        follow_redirects=True,
    )


def fetch_wardrobe(cookie: str, user_id: str) -> list[dict]:
    items: list[dict] = []
    with _client(cookie) as client:
        page = 1
        while True:
            resp = client.get(
                f"/api/v2/wardrobe/{user_id}/items",
                params={"page": page, "per_page": 96, "order": "relevance"},
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("items", [])
            items.extend(batch)
            pagination = data.get("pagination") or {}
            if page >= int(pagination.get("total_pages", 1)):
                break
            page += 1
    return items


def sync() -> str:
    with session_scope() as session:
        cookie = get_setting(session, "vinted_cookie")
        user_id = get_setting(session, "vinted_user_id")
    if not cookie or not user_id:
        return "Skipped: Vinted cookie/user ID not set (see /status)."

    listings = fetch_wardrobe(cookie, user_id)
    updated = added = 0

    with session_scope() as session:
        by_vinted_id = {
            i.vinted_id: i
            for i in session.exec(select(Item).where(Item.vinted_id.is_not(None)))
        }
        unlinked = [
            i for i in session.exec(select(Item).where(Item.vinted_id.is_(None)))
            if i.status in ("draft", "active", "offer")
        ]
        for lst in listings:
            vid = str(lst.get("id"))
            title = lst.get("title") or f"Vinted #{vid}"
            item = by_vinted_id.get(vid)
            if item is None:
                # prøv at koble annoncen til en eksisterende vare uden Vinted-ID
                best, best_score = None, 0.0
                for cand in unlinked:
                    score = SequenceMatcher(None, title.lower(), cand.name.lower()).ratio()
                    if score > best_score:
                        best, best_score = cand, score
                if best is not None and best_score >= 0.55:
                    item = best
                    item.vinted_id = vid
                    unlinked.remove(best)
                else:
                    # new listing created directly on Vinted — add as a review item
                    item = Item(
                        name=title,
                        vinted_id=vid,
                        status="active",
                        needs_review=True,
                        review_note="Found on Vinted with no local item — fill in purchase price/date.",
                    )
                    added += 1
            item.views = int(lst.get("view_count") or item.views)
            item.likes = int(lst.get("favourite_count") or item.likes)
            price = lst.get("price")
            if isinstance(price, dict) and price.get("amount"):
                item.list_price = float(price["amount"])
            item.vinted_url = lst.get("url") or item.vinted_url
            if lst.get("is_closed") and item.status in ("active", "offer"):
                item.status = "sold"
                item.needs_review = True
                item.review_note = "Closed on Vinted — confirm sale price/date."
            session.add(item)
            updated += 1
        session.commit()
        photos = _backfill_photos(session, listings)
    return f"Synced {updated} listings ({added} new from Vinted, {photos} photos fetched)."


def _backfill_photos(session, listings: list[dict]) -> int:
    """Henter første annonce-foto fra Vinteds CDN til varer uden billeder,
    så varelisten får miniaturer selv for varer oprettet før appen."""
    photo_urls = {}
    for lst in listings:
        if lst.get("photos"):
            p = lst["photos"][0]
            url = p.get("full_size_url") or p.get("url")
            if url:
                photo_urls[str(lst["id"])] = url

    items_with_images = {
        img.item_id for img in session.exec(select(ItemImage))
    }
    fetched = 0
    for item in session.exec(select(Item).where(Item.vinted_id.is_not(None))):
        url = photo_urls.get(item.vinted_id)
        if not url or item.id in items_with_images:
            continue
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True,
                             headers={"User-Agent": UA})
            resp.raise_for_status()
        except httpx.HTTPError:
            continue
        fname = f"{item.id}/vinted_{item.vinted_id}.jpg"
        dest = config.MEDIA_DIR / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        session.add(ItemImage(item_id=item.id, kind="raw", filename=fname, gen_status="none"))
        fetched += 1
    session.commit()
    return fetched


def probe(cookie: str, user_id: str) -> str:
    """Bruges af /status-siden til at teste en nyindsat cookie med det samme."""
    try:
        listings = fetch_wardrobe(cookie, user_id)
        return f"OK — found {len(listings)} listings."
    except httpx.HTTPStatusError as exc:
        return f"Error {exc.response.status_code}: the cookie is probably expired or the user ID is wrong."
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        return f"Fejl: {exc}"
