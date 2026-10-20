"""Tiny SVG line charts for docs/EVAL.md (no plotting dependency)."""

from __future__ import annotations

from html import escape
from pathlib import Path

PALETTE = ["#0E7C66", "#F59E0B", "#6366F1", "#DC2626", "#0EA5E9", "#7C3AED"]


def line_chart(
    series: dict[str, list[float]],
    path: Path,
    title: str,
    y_label: str,
    vline: int | None = None,
    vline_label: str = "",
    width: int = 760,
    height: int = 360,
) -> Path:
    pad_l, pad_r, pad_t, pad_b = 56, 200, 40, 44
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    n = max((len(v) for v in series.values()), default=1)
    ymax = max((max(v) for v in series.values() if v), default=1.0) or 1.0
    ymax = min(1.0, round(ymax + 0.05, 1)) if ymax <= 1 else ymax

    def x(i: int) -> float:
        return pad_l + (w * i / max(1, n - 1))

    def y(v: float) -> float:
        return pad_t + h - h * (v / ymax)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="Inter, sans-serif" '
        f'font-size="12"><rect width="100%" height="100%" fill="#FAFAF7"/>',
        f'<text x="{pad_l}" y="22" font-size="15" font-weight="600" fill="#111827">{escape(title)}</text>',
    ]
    for k in range(6):
        v = ymax * k / 5
        out.append(f'<line x1="{pad_l}" x2="{pad_l + w}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#E5E7EB"/>')
        out.append(f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end" fill="#6B7280">{v:.2f}</text>')
    out.append(f'<text x="{pad_l + w / 2}" y="{height - 10}" text-anchor="middle" fill="#6B7280">dia</text>')
    out.append(
        f'<text x="14" y="{pad_t + h / 2}" transform="rotate(-90 14 {pad_t + h / 2})" text-anchor="middle" '
        f'fill="#6B7280">{escape(y_label)}</text>'
    )
    if vline is not None:
        out.append(
            f'<line x1="{x(vline):.1f}" x2="{x(vline):.1f}" y1="{pad_t}" y2="{pad_t + h}" stroke="#111827" '
            f'stroke-dasharray="4 4"/><text x="{x(vline) + 4:.1f}" y="{pad_t + 12}" fill="#111827">'
            f"{escape(vline_label)}</text>"
        )
    for i, (name, values) in enumerate(series.items()):
        color = PALETTE[i % len(PALETTE)]
        pts = " ".join(f"{x(k):.1f},{y(v):.1f}" for k, v in enumerate(values))
        out.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/>')
        ly = pad_t + 16 + 20 * i
        out.append(
            f'<line x1="{pad_l + w + 16}" x2="{pad_l + w + 36}" y1="{ly}" y2="{ly}" stroke="{color}" '
            f'stroke-width="3"/><text x="{pad_l + w + 42}" y="{ly + 4}" fill="#111827">{escape(name)}</text>'
        )
    out.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path
