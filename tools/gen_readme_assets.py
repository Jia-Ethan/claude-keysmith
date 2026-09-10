#!/usr/bin/env python3
"""Generate README result charts for claude-keysmith.

Hero and architecture illustrations are authored separately (webp).
This script writes:

  docs/assets/readme/results-{zh,en}-{light,dark}.svg

Same-day Fable 5.1 measurement: v7.1 1/4 → current 3/4.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"
OUT.mkdir(parents=True, exist_ok=True)

DARK = {
    "bg": "#171A1D",
    "panel": "#1E2225",
    "stroke": "#3D4346",
    "axis": "#777E81",
    "fg": "#ECE8DF",
    "muted": "#AAA69E",
    "tick": "#D4D0C7",
    "prev": "#9AAFC2",
    "curr": "#C99C84",
}
LIGHT = {
    "bg": "#F7F4EE",
    "panel": "#FFFcf7",
    "stroke": "#D9D3C8",
    "axis": "#8A847A",
    "fg": "#2C2A26",
    "muted": "#6F6A62",
    "tick": "#4A4640",
    "prev": "#7E93A6",
    "curr": "#B07D62",
}

FONT = "Charter, Georgia, 'Times New Roman', STSong, 'Songti SC', 'Noto Serif CJK SC', serif"
PREV, CURR, MAXIMUM = 1, 3, 4


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def trend_svg(theme: str, lang: str) -> str:
    t = LIGHT if theme == "light" else DARK
    w, h = 1600, 880
    plot = dict(x=150, y=160, w=1260, h=550)
    if lang == "en":
        title = "Full deliveries on the same 4 prompts"
        subtitle = "One model · count only complete artifacts"
        prev_lab, curr_lab = "v7.1", "Current"
        y_lab = "Complete artifacts (out of 4)"
        foot = "Same-day comparison. A cell counts only when the requested artifact is present."
        legend_prev, legend_curr = "v7.1", "Current"
    else:
        title = "同一批 4 题的完整交付"
        subtitle = "同一模型 · 只统计完整交出产物的题数"
        prev_lab, curr_lab = "v7.1", "当前"
        y_lab = "完整交出产物的题数（共 4 题）"
        foot = "同日对照。一题只有在请求的产物实际出现时才计入。"
        legend_prev, legend_curr = "v7.1", "当前"
    prev_val, curr_val = f"{PREV}/{MAXIMUM}", f"{CURR}/{MAXIMUM}"

    def y_of(value: float) -> float:
        return plot["y"] + plot["h"] * (1 - value / MAXIMUM)

    bar_w = 180
    cx_prev = plot["x"] + plot["w"] * 0.32
    cx_curr = plot["x"] + plot["w"] * 0.68
    y_base = y_of(0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc" font-family="{FONT}">',
        f'<title id="title">{esc(title)}</title>',
        f'<desc id="desc">{esc(subtitle)}</desc>',
        f'<rect width="{w}" height="{h}" fill="{t["bg"]}"/>',
        f'<rect x="55" y="110" width="1490" height="665" rx="4" fill="{t["panel"]}" stroke="{t["stroke"]}"/>',
        f'<text x="780" y="60" text-anchor="middle" font-size="32" font-weight="500" fill="{t["fg"]}">{esc(title)}</text>',
        f'<text x="780" y="92" text-anchor="middle" font-size="20" fill="{t["muted"]}">{esc(subtitle)}</text>',
    ]
    for tick in range(0, MAXIMUM + 1):
        gy = y_of(tick)
        parts.append(
            f'<line x1="{plot["x"]}" y1="{gy:.1f}" x2="{plot["x"] + plot["w"]}" y2="{gy:.1f}" stroke="{t["stroke"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{plot["x"] - 18}" y="{gy + 8:.1f}" text-anchor="end" font-size="24" fill="{t["tick"]}">{tick}</text>'
        )
    parts.append(
        f'<line x1="{plot["x"]}" y1="{plot["y"]}" x2="{plot["x"]}" y2="{y_base:.1f}" stroke="{t["axis"]}" stroke-width="1.5"/>'
    )
    parts.append(
        f'<line x1="{plot["x"]}" y1="{y_base:.1f}" x2="{plot["x"] + plot["w"]}" y2="{y_base:.1f}" stroke="{t["axis"]}" stroke-width="1.5"/>'
    )
    parts.append(
        f'<text x="40" y="435" transform="rotate(-90 40 435)" text-anchor="middle" font-size="24" fill="{t["tick"]}">{esc(y_lab)}</text>'
    )

    def bar(cx: float, top: float, color: str, label: str, value: str) -> None:
        parts.append(
            f'<rect x="{cx - bar_w / 2:.1f}" y="{top:.1f}" width="{bar_w}" height="{y_base - top:.1f}" rx="4" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{top - 18:.1f}" text-anchor="middle" font-size="28" font-weight="500" fill="{color}">{esc(value)}</text>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{y_base + 42:.1f}" text-anchor="middle" font-size="24" fill="{t["tick"]}">{esc(label)}</text>'
        )

    bar(cx_prev, y_of(PREV), t["prev"], prev_lab, prev_val)
    bar(cx_curr, y_of(CURR), t["curr"], curr_lab, curr_val)
    parts.append(f'<rect x="1180" y="128" width="14" height="14" rx="2" fill="{t["prev"]}"/>')
    parts.append(f'<text x="1204" y="141" font-size="22" fill="{t["tick"]}">{esc(legend_prev)}</text>')
    parts.append(f'<rect x="1360" y="128" width="14" height="14" rx="2" fill="{t["curr"]}"/>')
    parts.append(f'<text x="1384" y="141" font-size="22" fill="{t["tick"]}">{esc(legend_curr)}</text>')
    parts.append(f'<text x="780" y="858" text-anchor="middle" font-size="18" fill="{t["muted"]}">{esc(foot)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    for lang in ("zh", "en"):
        for theme in ("light", "dark"):
            path = OUT / f"results-{lang}-{theme}.svg"
            path.write_text(trend_svg(theme, lang), encoding="utf-8")
            print(path.relative_to(ROOT), path.stat().st_size, "bytes")
    for stale in OUT.glob("pass-trend-*.svg"):
        stale.unlink()
        print("removed", stale.relative_to(ROOT))


if __name__ == "__main__":
    main()
