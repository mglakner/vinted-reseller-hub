"""Generates suggested Vinted title and description from an item's fields.
Deliberately template-based (no AI call) — fast, free and predictable."""
import re

from .models import Item

CONDITION_TEXT = {
    "New with tags": "Brand new with tags.",
    "Good condition": "In really good condition — no notable flaws or wear.",
    "Used - good": "Used, but in good condition. See the photos for detail.",
    "Worn": "Shows signs of use — priced accordingly.",
}

SIZE_RE = re.compile(r"(?:size|str)\.?\s*([A-Za-z0-9/ .½]+)$", re.IGNORECASE)


def suggest_title(item: Item) -> str:
    parts = []
    if item.brand and item.brand.lower() not in item.name.lower():
        parts.append(item.brand)
    parts.append(item.name)
    return " ".join(parts)[:70]


def suggest_description(item: Item) -> str:
    """English, copy-paste ready. Exactly two emojis (🏷️ price, 💬 CTA),
    no mention of thrift/secondhand sourcing, and no invented material/condition
    facts (only the Condition value you set)."""
    lines = []
    name_size = SIZE_RE.search(item.name)
    header = item.name if not name_size else item.name[: name_size.start()].strip(" -–")
    if item.brand:
        lines.append(f"{header} by {item.brand}.")
    else:
        lines.append(f"{header}.")
    if name_size:
        lines.append(f"Size: {name_size.group(1).strip()}.")
    cond = CONDITION_TEXT.get(item.condition)
    if cond:
        lines.append(cond)
    lines.append("")
    lines.append("🏷️ Fair price — feel free to ask any questions.")
    lines.append("💬 From a smoke- and pet-free home. Check my other listings — bundle discount on multiple items.")
    return "\n".join(lines)
