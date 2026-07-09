"""Builds a "listing package" for an item: everything Vinted's new-listing form
needs (title, description, price, category id, brand id, size, photos).

Used by the assisted listing flow: the app exposes the package as JSON, and a
bookmarklet / userscript fills Vinted's form from it. Everything here is
READ-only against Vinted — nothing is published from here.
"""
import json
import time
from difflib import SequenceMatcher

import httpx
from sqlmodel import Session, select

from . import auth, config
from .db import get_setting
from .listing_text import suggest_description, suggest_title
from .models import Item, ItemImage

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

CATALOG_CACHE = config.DATA_DIR / "vinted_catalogs.json"
CACHE_TTL = 60 * 60 * 24  # 1 day

# App category -> Vinted root-category code (best guess; you confirm/adjust the
# final category in Vinted before publishing).
CATEGORY_ROOT = {
    "Menswear": "MENS",
    "Womenswear": "WOMENS",
    "Shoes": "FOOTWEAR",
    "Bags": "BAGS_BACKPACKS",
    "Accessories": "ACCESSORIES_JEWELLERY",
    "Homeware": "HOME",
    "Electronics": "ELECTRONICS",
    "Other": None,
}


def _client(cookie: str) -> httpx.Client:
    return httpx.Client(
        base_url=f"https://{config.VINTED_DOMAIN}",
        headers={"User-Agent": UA, "Accept": "application/json", "Cookie": cookie},
        timeout=30, follow_redirects=True,
    )


def load_catalogs(session: Session, force: bool = False) -> dict | None:
    if not force and CATALOG_CACHE.exists() and time.time() - CATALOG_CACHE.stat().st_mtime < CACHE_TTL:
        return json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
    cookie = get_setting(session, "vinted_cookie")
    if not cookie:
        return json.loads(CATALOG_CACHE.read_text(encoding="utf-8")) if CATALOG_CACHE.exists() else None
    with _client(cookie) as client:
        resp = client.get("/api/v2/item_upload/catalogs")
        resp.raise_for_status()
        data = resp.json()
    CATALOG_CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def _flatten(nodes: list[dict], acc: list[dict]) -> None:
    for n in nodes:
        kids = n.get("catalogs") or []
        if not kids:
            acc.append(n)
        _flatten(kids, acc)


# Keyword in the item name -> word(s) in Vinted's leaf titles. A match here is
# strong (the item IS a polo), so it's weighted heavily.
KEYWORD_MAP = {
    "polo": ["polo"],
    "t-shirt": ["t-shirt"], "tshirt": ["t-shirt"], "tee": ["t-shirt"],
    "shirt": ["shirt"],
    "sweater": ["sweater", "jumper"], "jumper": ["jumper", "knit"], "knit": ["jumper", "knit"],
    "hoodie": ["hoodie"], "crewneck": ["sweatshirt"], "sweatshirt": ["sweatshirt"],
    "long sleeve": ["long sleeve"], "longsleeve": ["long sleeve"],
    "trousers": ["trousers"], "pants": ["trousers"], "jeans": ["jeans"], "shorts": ["shorts"],
    "jacket": ["jacket"], "coat": ["coat"], "fleece": ["fleece"],
    "dress": ["dress"], "skirt": ["skirt"], "blazer": ["blazer"],
    "loafers": ["loafers"], "sneakers": ["sneakers", "trainers"], "trainers": ["trainers", "sneakers"],
    "boots": ["boots"], "heels": ["heels"], "sandals": ["sandals"],
    "shoes": ["shoes", "trainers"], "cap": ["cap", "hat"], "hat": ["hat", "cap"],
    "watch": ["watch"], "bag": ["bag"], "belt": ["belt"],
}


def guess_catalog(catalogs: dict, item: Item) -> dict | None:
    """Find the best leaf category within the item's root. Return only on
    reasonable confidence — otherwise None, so you pick it yourself (better
    than a confidently wrong guess)."""
    if not catalogs:
        return None
    root_code = CATEGORY_ROOT.get(item.category)
    roots = catalogs.get("catalogs", [])
    search_roots = [r for r in roots if r.get("code") == root_code] if root_code else roots
    leaves: list[dict] = []
    _flatten(search_roots or roots, leaves)
    if not leaves:
        return None

    name = item.name.lower()
    wanted_words: list[str] = []
    for keyword, targets in KEYWORD_MAP.items():
        if keyword in name:
            wanted_words += targets

    best, best_score = None, 0.0
    for leaf in leaves:
        title = (leaf.get("title") or "").lower()
        if not title:
            continue
        score = SequenceMatcher(None, name, title).ratio() * 0.5
        # strong boost if a keyword points at exactly this leaf title
        if wanted_words and any(w in title for w in wanted_words):
            score += 0.6
        if score > best_score:
            best, best_score = leaf, score
    # require either a keyword hit or a high text similarity
    return best if best_score >= 0.55 else None


def resolve_brand(session: Session, brand: str) -> dict | None:
    if not brand.strip():
        return None
    cookie = get_setting(session, "vinted_cookie")
    if not cookie:
        return None
    try:
        with _client(cookie) as client:
            resp = client.get("/api/v2/brands", params={"keyword": brand})
            resp.raise_for_status()
            brands = resp.json().get("brands", [])
    except httpx.HTTPError:
        return None
    for b in brands:
        if b.get("title", "").lower() == brand.lower():
            return {"id": b["id"], "title": b["title"]}
    return {"id": brands[0]["id"], "title": brands[0]["title"]} if brands else None


def _size_from_name(name: str) -> str:
    import re
    m = re.search(r"(?:size|str)\.?\s*([A-Za-z0-9/ .½]+)$", name, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def build_package(session: Session, item: Item, base_url: str) -> dict:
    catalogs = None
    try:
        catalogs = load_catalogs(session)
    except httpx.HTTPError:
        catalogs = None
    leaf = guess_catalog(catalogs, item) if catalogs else None
    brand = resolve_brand(session, item.brand)

    images = session.exec(select(ItemImage).where(ItemImage.item_id == item.id)).all()
    # prefer generated images, then raw
    ordered = [i for i in images if i.kind == "generated"] + [i for i in images if i.kind != "generated"]
    # each photo gets its own signed token so the userscript can fetch it without
    # the login cookie (SameSite blocks cookies on cross-domain requests).
    photo_urls = [
        f"{base_url}/media/{i.filename}?token={auth.make_resource_token('media', i.filename)}"
        for i in ordered
    ]

    return {
        "item_id": item.id,
        "title": suggest_title(item),
        "description": suggest_description(item),
        "price": item.list_price or item.expected_price or item.purchase_price,
        "currency": "DKK",
        "category": {
            "id": leaf.get("id") if leaf else None,
            "title": leaf.get("title") if leaf else None,
            "path": leaf.get("path") if leaf else None,
            "needs_size": bool(leaf and leaf.get("size_field_visibility")),
            "size_group_id": (leaf.get("multiple_size_group_ids") or [None])[0] if leaf else None,
        },
        "brand": brand,
        "size_hint": _size_from_name(item.name),
        "condition": item.condition,
        "photos": photo_urls,
    }
