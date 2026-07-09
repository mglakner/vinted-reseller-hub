import logging
import mimetypes
import secrets
import shutil
import time
import urllib.parse
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, desc, select

from PIL import Image, ImageOps

from . import auth, charts, config, listing_text, shots, vinted_listing
from .bookmarklet import BOOKMARKLET
from .db import engine, get_setting, init_db, set_setting
from .exporter import export_xlsx
from .jobs import scheduler, start_scheduler
from .metrics import compute_dashboard, group_stats, suggest_price
from .models import STATUS_LABELS, Expense, Item, ItemImage, JobRun

logging.basicConfig(level=logging.INFO)

BASE = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
templates.env.globals["SHOT_LABELS"] = {s.key: s.label for s in shots.SHOTS}


def get_session():
    with Session(engine) as session:
        yield session


def fmt_money(value) -> str:
    if value is None:
        return "–"
    number = f"{value:,.0f}".replace(",", " ")  # space thousands separator (locale-neutral)
    return f"{number} {config.CURRENCY}".strip()


# filter is named "kr" for backwards-compat with existing templates
templates.env.filters["kr"] = fmt_money


@app.middleware("http")
async def require_login(request: Request, call_next):
    # Uden APP_PASSWORD (kun til lokal udvikling) er login slået fra.
    open_paths = ("/login", "/static", "/manifest.webmanifest", "/health")
    path = request.url.path
    # Pakke- og medie-ruter håndhæver selv adgang (login ELLER signeret token),
    # så userscriptet kan hente dem på tværs af domæner uden session-cookie.
    self_guarded = path.endswith("/vinted-package.json") or path.startswith("/media/")
    if (
        config.APP_PASSWORD
        and not path.startswith(open_paths)
        and not self_guarded
        and not auth.is_authenticated(request)
    ):
        return RedirectResponse(url="/login", status_code=303)
    response = await call_next(request)
    # Appen ligger bag Cloudflare. Undgå at Cloudflare cacher dynamiske svar
    # (og cacher fejl under deploys). Statiske filer får kort levetid.
    if request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "public, max-age=300"
    else:
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# --- Login ---

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    if config.APP_PASSWORD and secrets.compare_digest(password, config.APP_PASSWORD):
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie(
            auth.COOKIE_NAME, auth.make_session_cookie(),
            max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax",
        )
        return resp
    time.sleep(1)
    return templates.TemplateResponse(request, "login.html", {"error": "Forkert kodeord."})


@app.get("/health")
def health():
    return {"ok": True}


# --- Dashboard ---

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    d = compute_dashboard(session)
    chart = charts.bar_chart(d.monthly_profit) if any(v for _, v in d.monthly_profit) else ""
    stale_suggestions = {i.id: suggest_price(i) for i in d.stale_items}
    return templates.TemplateResponse(request, "dashboard.html", {
        "d": d, "chart": chart, "stale_suggestions": stale_suggestions,
    })


@app.get("/insights", response_class=HTMLResponse)
def insights(request: Request, session: Session = Depends(get_session)):
    items = list(session.exec(select(Item)))
    brands = group_stats(items, lambda i: i.brand)
    categories = group_stats(items, lambda i: i.category)
    brand_chart = charts.hbar_chart([(g.name, g.profit) for g in brands[:8] if g.profit > 0])
    return templates.TemplateResponse(request, "insights.html", {
        "brands": brands, "categories": categories, "brand_chart": brand_chart,
    })


# --- Items ---

SORTS = {
    "newest": lambda i: -(i.id or 0),
    "profit": lambda i: -(i.net_profit or -9999),
    "days": lambda i: -(i.days_listed or -1),
    "name": lambda i: i.name.lower(),
}


@app.get("/items", response_class=HTMLResponse)
def items_list(
    request: Request,
    status: str = "",
    q: str = "",
    sort: str = "newest",
    session: Session = Depends(get_session),
):
    query = select(Item)
    if status:
        query = query.where(Item.status == status)
    if q:
        query = query.where(Item.name.contains(q) | Item.brand.contains(q))
    items = sorted(session.exec(query), key=SORTS.get(sort, SORTS["newest"]))

    thumbs: dict[int, str] = {}
    for img in session.exec(select(ItemImage).order_by(ItemImage.id)):
        thumbs.setdefault(img.item_id, img.filename)
    return templates.TemplateResponse(
        request, "items.html",
        {"items": items, "status": status, "q": q, "sort": sort, "thumbs": thumbs},
    )


@app.get("/items/new", response_class=HTMLResponse)
def item_new(request: Request):
    return templates.TemplateResponse(request, "item_form.html", {"item": None, "today": date.today().isoformat()})


@app.post("/items/new")
async def item_create(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    brand: str = Form(""),
    category: str = Form(""),
    condition: str = Form(""),
    purchase_price: float = Form(0.0),
    purchase_date: str = Form(""),
    expected_price: Optional[float] = Form(None),
    photos: list[UploadFile] = Form([]),
):
    item = Item(
        name=name.strip(),
        brand=brand.strip(),
        category=category,
        condition=condition,
        purchase_price=purchase_price,
        purchase_date=date.fromisoformat(purchase_date) if purchase_date else date.today(),
        expected_price=expected_price,
        status="draft",
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    for photo in photos:
        if not photo.filename:
            continue
        suffix = Path(photo.filename).suffix.lower() or ".jpg"
        fname = f"{item.id}/raw_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}{suffix}"
        dest = config.MEDIA_DIR / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await photo.read())
        session.add(ItemImage(item_id=item.id, kind="raw", filename=fname, gen_status="none"))
    session.commit()
    return RedirectResponse(url=f"/items/{item.id}", status_code=303)


@app.get("/items/{item_id}", response_class=HTMLResponse)
def item_detail(request: Request, item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if not item:
        return RedirectResponse(url="/items", status_code=303)
    images = list(session.exec(select(ItemImage).where(ItemImage.item_id == item_id)))
    has_raw = any(i.kind == "raw" for i in images)
    image_status = {i.shot_key: i.gen_status for i in images if i.kind == "generated"}
    base = str(request.base_url).rstrip("/")
    pkg_token = auth.make_resource_token("pkg", item_id)
    package_url = f"{base}/items/{item_id}/vinted-package.json?token={pkg_token}"
    # URL-encode hele pakke-URL'en, så dens eget ?token= ikke bliver læst
    # som en separat parameter på vinted.dk-URL'en.
    vh = urllib.parse.quote(package_url, safe="")
    return templates.TemplateResponse(request, "item_detail.html", {
        "item": item,
        "images": images,
        "suggested_title": listing_text.suggest_title(item),
        "suggested_description": listing_text.suggest_description(item),
        "price_suggestion": suggest_price(item) if (item.days_listed or 0) >= 30 and item.offer_count == 0 else None,
        "vinted_new_url": f"https://{config.VINTED_DOMAIN}/items/new?vh={vh}",
        "shots": shots.SHOTS,
        "core_keys": shots.CORE_KEYS,
        "image_status": image_status,
        "has_raw": has_raw,
        "credits_per_shot": shots.CREDITS_PER_SHOT,
    })


@app.post("/items/{item_id}/generate")
def item_generate(
    request: Request,
    item_id: int,
    session: Session = Depends(get_session),
    shot_keys: list[str] = Form(default=[]),
):
    item = session.get(Item, item_id)
    if not item:
        return Response(status_code=404)
    if not any(
        i.kind == "raw" for i in session.exec(select(ItemImage).where(ItemImage.item_id == item_id))
    ):
        return RedirectResponse(url=f"/items/{item_id}", status_code=303)
    # fjern tidligere genererede/fejlede udgaver af de valgte shots, så de kan laves igen
    for key in shot_keys:
        if key not in shots.SHOTS_BY_KEY:
            continue
        for old in session.exec(select(ItemImage).where(
            ItemImage.item_id == item_id, ItemImage.kind == "generated", ItemImage.shot_key == key
        )):
            if old.filename:
                (config.MEDIA_DIR / old.filename).unlink(missing_ok=True)
            session.delete(old)
        session.add(ItemImage(item_id=item_id, kind="generated", shot_key=key, gen_status="pending"))
    session.commit()
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@app.get("/items/{item_id}/vinted-package.json")
def item_vinted_package(
    request: Request, item_id: int, token: str = "", session: Session = Depends(get_session)
):
    if config.APP_PASSWORD and not auth.is_authenticated(request) and not auth.verify_resource_token(token, "pkg", item_id):
        return Response(status_code=403)
    item = session.get(Item, item_id)
    if not item:
        return Response(status_code=404)
    base = str(request.base_url).rstrip("/")
    pkg = vinted_listing.build_package(session, item, base)
    # CORS: tillad at bookmarkletten (kører på vinted.dk) læser svaret.
    # Ruten er stadig token-beskyttet, så CORS åbner ikke for uvedkommende.
    return JSONResponse(pkg, headers={"Access-Control-Allow-Origin": "*"})


@app.post("/items/{item_id}/listed")
def item_mark_listed(
    item_id: int,
    session: Session = Depends(get_session),
    list_price: float = Form(...),
    listed_date: str = Form(""),
):
    item = session.get(Item, item_id)
    if item:
        item.status = "active"
        item.list_price = list_price
        item.listed_date = date.fromisoformat(listed_date) if listed_date else date.today()
        session.add(item)
        session.commit()
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/delete")
def item_delete(item_id: int, session: Session = Depends(get_session)):
    item = session.get(Item, item_id)
    if item:
        for img in session.exec(select(ItemImage).where(ItemImage.item_id == item_id)):
            session.delete(img)
        session.delete(item)
        session.commit()
        # ryd varens fotomappe (+ evt. cachede miniaturer)
        shutil.rmtree(config.MEDIA_DIR / str(item_id), ignore_errors=True)
        shutil.rmtree(config.DATA_DIR / "thumbs" / str(item_id), ignore_errors=True)
    return RedirectResponse(url="/items", status_code=303)


@app.post("/items/{item_id}/edit")
def item_edit(
    item_id: int,
    session: Session = Depends(get_session),
    name: str = Form(...),
    brand: str = Form(""),
    category: str = Form(""),
    condition: str = Form(""),
    purchase_price: float = Form(0.0),
    purchase_date: str = Form(""),
    bump_cost: float = Form(0.0),
    list_price: Optional[float] = Form(None),
    listed_date: str = Form(""),
    status: str = Form("draft"),
    sale_price: Optional[float] = Form(None),
    sale_date: str = Form(""),
    vinted_fee: float = Form(0.0),
    shipping_cost: float = Form(0.0),
    vinted_id: str = Form(""),
    notes: str = Form(""),
):
    item = session.get(Item, item_id)
    if not item:
        return RedirectResponse(url="/items", status_code=303)
    item.name = name.strip()
    item.brand = brand.strip()
    item.category = category
    item.condition = condition
    item.purchase_price = purchase_price
    item.purchase_date = date.fromisoformat(purchase_date) if purchase_date else None
    item.bump_cost = bump_cost
    item.list_price = list_price
    item.listed_date = date.fromisoformat(listed_date) if listed_date else None
    item.status = status
    item.sale_price = sale_price
    item.sale_date = date.fromisoformat(sale_date) if sale_date else None
    item.vinted_fee = vinted_fee
    item.shipping_cost = shipping_cost
    item.vinted_id = vinted_id.strip() or None
    item.notes = notes.strip()
    item.needs_review = False
    item.review_note = ""
    session.add(item)
    session.commit()
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@app.post("/items/{item_id}/sold")
def item_mark_sold(
    item_id: int,
    session: Session = Depends(get_session),
    sale_price: float = Form(...),
    sale_date: str = Form(""),
):
    item = session.get(Item, item_id)
    if item:
        item.status = "sold"
        item.sale_price = sale_price
        item.sale_date = date.fromisoformat(sale_date) if sale_date else date.today()
        item.needs_review = False
        item.review_note = ""
        session.add(item)
        session.commit()
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


# --- Medier (fotos) ---

@app.get("/media/{path:path}")
def media(path: str, request: Request, token: str = ""):
    if config.APP_PASSWORD and not auth.is_authenticated(request) and not auth.verify_resource_token(token, "media", path):
        return Response(status_code=403)
    file = (config.MEDIA_DIR / path).resolve()
    if not file.is_file() or config.MEDIA_DIR.resolve() not in file.parents:
        return Response(status_code=404)
    mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    return FileResponse(file, media_type=mime, headers={"Access-Control-Allow-Origin": "*"})


@app.get("/thumb/{path:path}")
def thumb(path: str):
    """320px-miniature, genereres første gang og caches på disk."""
    src = (config.MEDIA_DIR / path).resolve()
    if not src.is_file() or config.MEDIA_DIR.resolve() not in src.parents:
        return Response(status_code=404)
    cache = config.DATA_DIR / "thumbs" / Path(path).with_suffix(".jpg")
    if not cache.is_file() or cache.stat().st_mtime < src.stat().st_mtime:
        cache.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((320, 320))
            im.save(cache, "JPEG", quality=82)
    return FileResponse(cache, media_type="image/jpeg")


# --- Omkostninger ---

@app.get("/expenses", response_class=HTMLResponse)
def expenses_list(request: Request, session: Session = Depends(get_session)):
    expenses = list(session.exec(select(Expense).order_by(desc(Expense.id))))
    total = sum(e.amount for e in expenses)
    return templates.TemplateResponse(request, "expenses.html", {
        "expenses": expenses, "total": total, "today": date.today().isoformat(),
    })


@app.post("/expenses")
def expense_create(
    session: Session = Depends(get_session),
    name: str = Form(...),
    amount: float = Form(...),
    spent_date: str = Form(""),
):
    session.add(Expense(
        name=name.strip(),
        amount=amount,
        spent_date=date.fromisoformat(spent_date) if spent_date else date.today(),
    ))
    session.commit()
    return RedirectResponse(url="/expenses", status_code=303)


@app.post("/expenses/{expense_id}/delete")
def expense_delete(expense_id: int, session: Session = Depends(get_session)):
    expense = session.get(Expense, expense_id)
    if expense:
        session.delete(expense)
        session.commit()
    return RedirectResponse(url="/expenses", status_code=303)


# --- Eksport ---

@app.get("/export.xlsx")
def export(session: Session = Depends(get_session)):
    data = export_xlsx(session)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Vinted Accounts {date.today()}.xlsx"'},
    )


# --- Status/admin (til Mads) ---

@app.get("/status", response_class=HTMLResponse)
def status_page(request: Request, session: Session = Depends(get_session)):
    runs = list(session.exec(select(JobRun).order_by(desc(JobRun.id)).limit(20)))
    pending_images = len(session.exec(
        select(ItemImage).where(ItemImage.gen_status.in_(("pending", "error")))
    ).all())
    ctx = {
        "runs": runs,
        "pending_images": pending_images,
        "vinted_cookie_set": bool(get_setting(session, "vinted_cookie")),
        "vinted_user_id": get_setting(session, "vinted_user_id"),
        "gmail_configured": bool(config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD),
        "higgsfield_backend": config.HIGGSFIELD_BACKEND or "(ikke sat)",
        "probe_result": request.query_params.get("probe", ""),
        "bookmarklet": BOOKMARKLET,
    }
    return templates.TemplateResponse(request, "status.html", ctx)


@app.post("/status/vinted")
def status_set_vinted(
    session: Session = Depends(get_session),
    cookie: str = Form(""),
    user_id: str = Form(""),
):
    from .jobs import vinted_sync

    if cookie.strip():
        set_setting(session, "vinted_cookie", cookie.strip())
    if user_id.strip():
        set_setting(session, "vinted_user_id", user_id.strip())
    cookie_now = get_setting(session, "vinted_cookie")
    user_now = get_setting(session, "vinted_user_id")
    probe = vinted_sync.probe(cookie_now, user_now) if cookie_now and user_now else "Both cookie and user ID are required."
    return RedirectResponse(url=f"/status?probe={probe}", status_code=303)


@app.get("/manifest.webmanifest")
def manifest():
    return {
        "name": "Vinted Hub",
        "short_name": "VintedHub",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#101014",
        "theme_color": "#101014",
        "icons": [{"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }
