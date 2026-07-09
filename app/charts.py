"""Server-renderede SVG-diagrammer. Farver via CSS-variabler, så de følger
lys/mørk tilstand. Én serie, én farve — ingen legend nødvendig."""
from xml.sax.saxutils import escape


def _nice_ticks(vmax: float, n: int = 3) -> list[float]:
    if vmax <= 0:
        return [0]
    step = vmax / n
    magnitude = 10 ** len(str(int(step))) / 10
    step = max(round(step / magnitude) * magnitude, magnitude)
    ticks, t = [0.0], 0.0
    while t < vmax:
        t += step
        ticks.append(t)
    return ticks


def bar_chart(data: list[tuple[str, float]], width: int = 640, height: int = 220) -> str:
    """Søjlediagram af (label, værdi). Tynde søjler, afrundede topper,
    værdi-labels kun når der er få søjler med indhold."""
    if not data:
        return ""
    pad_l, pad_r, pad_t, pad_b = 44, 8, 18, 26
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    vmax = max((v for _, v in data), default=0)
    ticks = _nice_ticks(vmax)
    vscale = ticks[-1] or 1

    n = len(data)
    slot = plot_w / n
    bar_w = min(36, slot * 0.55)
    label_all = sum(1 for _, v in data if v > 0) <= 4

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'style="width:100%;height:auto;font-family:inherit" '
        f'aria-label="Profit per month">'
    ]
    for t in ticks:
        y = pad_t + plot_h * (1 - t / vscale)
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="var(--line)" stroke-width="1"/>'
            f'<text x="{pad_l - 6}" y="{y + 3:.1f}" text-anchor="end" '
            f'font-size="10" fill="var(--muted)">{t:,.0f}</text>'.replace(",", ".")
        )
    for idx, (label, value) in enumerate(data):
        cx = pad_l + slot * idx + slot / 2
        bar_h = plot_h * (value / vscale) if vscale else 0
        y = pad_t + plot_h - bar_h
        title = f"{escape(label)}: {value:,.0f} kr".replace(",", ".")
        if bar_h > 0:
            parts.append(
                f'<rect x="{cx - bar_w / 2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
                f'rx="4" fill="var(--accent)"><title>{title}</title></rect>'
            )
            # afrundede topper, flad bund: dæk nederste hjørner
            if bar_h > 4:
                parts.append(
                    f'<rect x="{cx - bar_w / 2:.1f}" y="{pad_t + plot_h - 4:.1f}" '
                    f'width="{bar_w:.1f}" height="4" fill="var(--accent)"/>'
                )
        if label_all and value > 0:
            parts.append(
                f'<text x="{cx:.1f}" y="{y - 5:.1f}" text-anchor="middle" '
                f'font-size="10" font-weight="600" fill="var(--ink-2)">{value:,.0f}</text>'.replace(",", ".")
            )
        parts.append(
            f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="middle" '
            f'font-size="10" fill="var(--ink-2)">{escape(label)}</text>'
        )
    parts.append(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" '
        f'stroke="var(--ink-2)" stroke-width="1"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def hbar_chart(data: list[tuple[str, float]], width: int = 640, unit: str = "kr") -> str:
    """Vandrette søjler til kategori-/mærkefordeling (magnitude, én farve)."""
    if not data:
        return ""
    row_h, pad_t = 26, 4
    label_w, value_w = 150, 70
    height = pad_t * 2 + row_h * len(data)
    plot_w = width - label_w - value_w
    vmax = max((v for _, v in data), default=0) or 1

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'style="width:100%;height:auto;font-family:inherit" aria-label="Distribution">'
    ]
    for idx, (label, value) in enumerate(data):
        y = pad_t + row_h * idx
        bar = plot_w * (value / vmax)
        title = f"{escape(label)}: {value:,.0f} {unit}".replace(",", ".")
        parts.append(
            f'<text x="{label_w - 8}" y="{y + row_h / 2 + 3:.1f}" text-anchor="end" '
            f'font-size="11" fill="var(--ink)">{escape(label[:20])}</text>'
            f'<rect x="{label_w}" y="{y + 5:.1f}" width="{max(bar, 2):.1f}" height="{row_h - 10}" '
            f'rx="4" fill="var(--accent)"><title>{title}</title></rect>'
            f'<text x="{label_w + max(bar, 2) + 6:.1f}" y="{y + row_h / 2 + 3:.1f}" '
            f'font-size="10" font-weight="600" fill="var(--ink-2)">{value:,.0f}</text>'.replace(",", ".")
        )
    parts.append("</svg>")
    return "".join(parts)
