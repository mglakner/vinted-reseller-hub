"""Queue worker for product photos.

On an item you pick which shots to generate (see /items/{id}/generate), which
creates ItemImage rows with kind='generated', gen_status='pending' and a
shot_key. This worker takes the pending rows and generates each via the
Higgsfield hosted MCP (nano_banana_pro, reference photo + shot prompt),
watermarks 01–04, crops to 1080×1350 (macros keep 2K), and saves.

Requires HIGGSFIELD_BACKEND=mcp + one-time OAuth (see app/higgsfield_mcp.py).
"""
import asyncio
import json
import mimetypes
import re
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlmodel import select

from .. import config
from ..db import get_setting, session_scope
from ..models import Item, ItemImage
from ..shots import ASPECT, MODEL, SHOTS_BY_KEY, describe

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
IMG_URL_RE = re.compile(r"https://[^\s\"']+\.(?:png|jpe?g|webp)[^\s\"']*")

FONT_PATH = Path(__file__).resolve().parent.parent / "static" / "fonts" / "Lora-Regular.ttf"
TARGET_SIZE = (1080, 1350)  # 4:5


def _text_of(result) -> str:
    text = "\n".join(b.text for b in result.content if getattr(b, "type", "") == "text")
    if result.structuredContent:
        text += "\n" + json.dumps(result.structuredContent)
    return text


def _first_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(m.group(0)) if m else {}


async def _generate_shot(raw_path: Path, out_path: Path, prompt: str, resolution: str) -> None:
    from ..higgsfield_mcp import call_tool

    mime = mimetypes.guess_type(raw_path.name)[0] or "image/jpeg"

    up_text = _text_of(await call_tool("media_upload", {
        "method": "upload_url", "filename": raw_path.name, "content_type": mime,
    }))
    up = _first_json(up_text)
    upload_url = media_id = None
    holders = [up] + (up.get("uploads") or up.get("files") or []) if isinstance(up, dict) else []
    for cand in holders:
        if isinstance(cand, dict):
            upload_url = cand.get("upload_url") or cand.get("url") or upload_url
            media_id = cand.get("media_id") or cand.get("id") or media_id
    if not upload_url:
        m = re.search(r"https://[^\s\"']+", up_text)
        upload_url = m.group(0) if m else None
    if not media_id:
        ids = UUID_RE.findall(up_text)
        media_id = ids[0] if ids else None
    if not upload_url or not media_id:
        raise RuntimeError(f"media_upload response not understood: {up_text[:200]}")

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.put(upload_url, content=raw_path.read_bytes(), headers={"Content-Type": mime})
        r.raise_for_status()

    await call_tool("media_confirm", {"type": "image", "media_id": media_id})

    gen_text = _text_of(await call_tool("generate_image", {"params": {
        "model": MODEL, "prompt": prompt, "count": 1,
        "aspect_ratio": ASPECT, "resolution": resolution,
        "medias": [{"value": media_id, "role": "image"}],
    }}))
    job_ids = [u for u in UUID_RE.findall(gen_text) if u != media_id]
    if not job_ids:
        raise RuntimeError(f"generate_image gav intet job-id: {gen_text[:200]}")
    job_id = job_ids[0]

    deadline = time.monotonic() + 600
    status_text = ""
    while time.monotonic() < deadline:
        status_text = _text_of(await call_tool("job_status", {"jobId": job_id, "sync": True}))
        low = status_text.lower()
        if "completed" in low:
            break
        if any(k in low for k in ("failed", "nsfw", "ip_detected", "error")):
            raise RuntimeError(f"Generering fejlede: {status_text[:200]}")
    else:
        raise RuntimeError("Timed out waiting for the Higgsfield job.")

    urls = IMG_URL_RE.findall(status_text)
    if not urls:
        raise RuntimeError(f"No image URL in job result: {status_text[:200]}")

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        r = await client.get(urls[0])
        r.raise_for_status()
        out_path.write_bytes(r.content)


def _postprocess(path: Path, watermark: bool, resize_1080: bool, wm_text: str) -> None:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        if resize_1080:
            im = ImageOps.fit(im, TARGET_SIZE, Image.LANCZOS)
        if watermark and wm_text:
            _apply_watermark(im, wm_text)
        im.save(path, "PNG")


def _apply_watermark(im: Image.Image, text: str) -> None:
    """Lora 36px · #333 · 85% opacity · 20px from top · centered."""
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype(str(FONT_PATH), 36)
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), text, font=font)
    x = (im.size[0] - (box[2] - box[0])) // 2
    draw.text((x, 20), text, font=font, fill=(51, 51, 51, 216))
    im.paste(Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _reference_for(session, item: Item) -> Path | None:
    raw = session.exec(
        select(ItemImage).where(ItemImage.item_id == item.id, ItemImage.kind == "raw")
        .order_by(ItemImage.id)
    ).first()
    if not raw or not raw.filename:
        return None
    p = config.MEDIA_DIR / raw.filename
    return p if p.is_file() else None


def process_queue() -> str:
    if not config.HIGGSFIELD_BACKEND:
        with session_scope() as session:
            pending = len(session.exec(
                select(ItemImage).where(ItemImage.gen_status == "pending")
            ).all())
        return f"Skipped: Higgsfield not configured ({pending} queued)."

    with session_scope() as session:
        wm_text = get_setting(session, "watermark_text", config.WATERMARK_TEXT)
        queue = session.exec(
            select(ItemImage).where(
                ItemImage.kind == "generated", ItemImage.gen_status == "pending"
            ).limit(4)
        ).all()
        queue_ids = [img.id for img in queue]

    done = failed = 0
    for img_id in queue_ids:
        with session_scope() as session:
            img = session.get(ItemImage, img_id)
            item = session.get(Item, img.item_id)
            shot = SHOTS_BY_KEY.get(img.shot_key)
            ref = _reference_for(session, item)
            if shot is None or ref is None:
                img.gen_status = "error"
                img.gen_error = "Missing shot definition or reference photo."
                session.add(img)
                session.commit()
                failed += 1
                continue
            img.gen_status = "generating"
            session.add(img)
            session.commit()
            prompt = shot.prompt.format(desc=describe(item.brand, item.category))
            out_name = f"{item.id}/gen_{shot.key}.png"

        out_path = config.MEDIA_DIR / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            asyncio.run(_generate_shot(ref, out_path, prompt, shot.resolution))
            _postprocess(out_path, shot.watermark, shot.resize_1080, wm_text)
            with session_scope() as session:
                img = session.get(ItemImage, img_id)
                img.filename = out_name
                img.gen_status = "done"
                session.add(img)
                session.commit()
            done += 1
        except Exception as exc:  # noqa: BLE001 — one failure must not stop the queue
            with session_scope() as session:
                img = session.get(ItemImage, img_id)
                img.gen_status = "error"
                img.gen_error = str(exc)[:500]
                session.add(img)
                session.commit()
            failed += 1
    return f"Generated {done}, failed {failed}."
