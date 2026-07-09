"""The product-photo "shots" for the deterministic Higgsfield MCP pipeline.

There is no LLM in the loop filling [COLOR]/[LOGO] placeholders from an image
analysis. Instead the reference photo itself carries the item's colour/pattern/
logo, and the prompt fixes the COMPOSITION (flat lay, hanger, ghost mannequin,
etc.), background and lighting. Model: nano_banana_pro, 4:5 (= 1080×1350).
Watermark on shots 01–04 only.
"""
from dataclasses import dataclass

MODEL = "nano_banana_pro"
ASPECT = "4:5"

# Category -> English noun used in the prompt. The reference photo carries the rest.
CATEGORY_NOUN = {
    "Menswear": "garment",
    "Womenswear": "garment",
    "Shoes": "shoes",
    "Bags": "bag",
    "Accessories": "accessory",
    "Homeware": "item",
    "Electronics": "item",
}


@dataclass(frozen=True)
class Shot:
    key: str
    label: str          # shown in the UI
    prompt: str         # {desc} is filled from the item's fields
    watermark: bool
    resolution: str     # "1k" | "2k"
    resize_1080: bool   # True: crop to 1080×1350; False: keep the model's resolution
    core: bool          # part of the default selection


SHOTS: list[Shot] = [
    Shot("01_flat_lay", "Flat lay", (
        "Professional product flat lay photography of the exact {desc} from the "
        "reference image, unchanged. Laid perfectly flat on a warm cream off-white "
        "surface, sleeves/parts extended naturally, overhead top-down view, soft "
        "diffused studio lighting with a very subtle gentle shadow. Commercial "
        "fashion photography, no props, no text."
    ), watermark=True, resolution="1k", resize_1080=True, core=True),

    Shot("02_hanger", "Hanger", (
        "The exact {desc} from the reference image hanging on a slim minimal wooden "
        "hanger, unchanged. Hanging naturally, warm cream off-white background wall, "
        "very soft natural side lighting with a gentle shadow behind it. Editorial "
        "fashion product photography, no props, no text."
    ), watermark=True, resolution="1k", resize_1080=True, core=True),

    Shot("03_ghost_front", "Ghost mannequin (front)", (
        "Ghost mannequin invisible-torso front-view product photography of the exact "
        "{desc} from the reference image, unchanged. Floating and holding its natural "
        "shape, warm cream off-white background, very soft diffused studio lighting "
        "with a subtle gentle shadow. Professional e-commerce fashion photography, no text."
    ), watermark=True, resolution="1k", resize_1080=True, core=True),

    Shot("04_ghost_back", "Ghost mannequin (back)", (
        "Ghost mannequin invisible-torso rear-view product photography of the exact "
        "{desc} from the reference image, unchanged, showing the back. Floating and "
        "holding its natural shape, warm cream off-white background, very soft diffused "
        "studio lighting with a subtle gentle shadow. Professional e-commerce fashion "
        "photography, no text."
    ), watermark=True, resolution="1k", resize_1080=True, core=False),

    Shot("05_mannequin", "Mannequin", (
        "The exact {desc} from the reference image, unchanged, displayed on a vintage "
        "tailor's mannequin: cream linen torso, dark walnut jointed wooden arms, "
        "headless half-body on a black metal pole and base. Neutral grey-white studio "
        "background, soft diffused lighting. Editorial fashion product photography, no text."
    ), watermark=False, resolution="1k", resize_1080=True, core=False),

    Shot("06_logo_macro", "Logo macro (2K)", (
        "Extreme close-up macro detail photography of the logo/badge area of the exact "
        "{desc} from the reference image. 1:1 pixel-accurate fidelity to the reference, "
        "no blur, no pixelation, no artifacts. Crisp fabric texture and stitching, soft "
        "studio lighting revealing surface quality, neutral light background. Commercial "
        "fashion macro photography."
    ), watermark=False, resolution="2k", resize_1080=False, core=True),

    Shot("07_styled_flatlay", "Styled flatlay", (
        "Styled outfit flat lay, top-down overhead photography. The exact {desc} from "
        "the reference image laid flat and centered, unchanged, paired with tastefully "
        "matching clothing folded neatly to the side. Clean white or very light cream "
        "background, soft even diffused overhead lighting. Editorial minimal styling, "
        "commercial fashion photography, no other props, no text."
    ), watermark=False, resolution="1k", resize_1080=True, core=False),

    Shot("08_neck_label", "Neck label macro (2K)", (
        "Extreme close-up macro detail photography of the interior neck/brand label of "
        "the exact {desc} from the reference image. Woven label with all text crisp and "
        "fully legible, 1:1 pixel-accurate fidelity to the reference, no blur, no "
        "pixelation, no artifacts. Soft even studio lighting, neutral light background. "
        "Commercial fashion macro photography."
    ), watermark=False, resolution="2k", resize_1080=False, core=False),
]

SHOTS_BY_KEY = {s.key: s for s in SHOTS}
CORE_KEYS = [s.key for s in SHOTS if s.core]

# Higgsfield credits per generation (2 credits/shot for nano_banana_pro).
CREDITS_PER_SHOT = 2


def describe(brand: str, category: str) -> str:
    noun = CATEGORY_NOUN.get(category, "item")
    brand = (brand or "").strip()
    return f"{brand} {noun}".strip()
