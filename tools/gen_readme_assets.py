#!/usr/bin/env python3
"""Generate README SVG assets (light/dark pairs) for claude-keysmith.

Run:  python3 tools/gen_readme_assets.py
Outputs:
  docs/assets/readme/deploy-flow-{zh,en}-{light,dark}.svg
  docs/assets/readme/pass-trend-{zh,en}-{light,dark}.svg
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"
OUT.mkdir(parents=True, exist_ok=True)

LIGHT = {
    "bg": "#ffffff",
    "fg": "#24292f",
    "muted": "#57606a",
    "accent": "#0969da",
    "accent_soft": "#ddf4ff",
    "border": "#d0d7de",
    "good": "#1a7f37",
    "good_soft": "#dafbe1",
    "warn": "#9a6700",
    "warn_soft": "#fff8c5",
    "grid": "#eaeef2",
    "arrow": "#57606a",
}
DARK = {
    "bg": "#0d1117",
    "fg": "#e6edf3",
    "muted": "#8b949e",
    "accent": "#58a6ff",
    "accent_soft": "#121d2f",
    "border": "#30363d",
    "good": "#3fb950",
    "good_soft": "#12261e",
    "warn": "#d29922",
    "warn_soft": "#211d0e",
    "grid": "#21262d",
    "arrow": "#8b949e",
}

FONT = "-apple-system, 'Segoe UI', 'Noto Sans', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif"


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


FLOW_ZH = [
    ("1 预览", "install", "查看 CLAUDE.md import block、\n指令文件与备份计划", "accent"),
    ("2 写入", "--yes", "插入可卸载 import block，\n写入 keysmith/*.md", "accent"),
    ("3 验证", "新会话", "开新 Claude Code 会话，\nstatus 确认 import 已加载", "good"),
    ("4 撤销", "uninstall", "预览并移除同名 import block，\n指令文件一并卸载", "good"),
]
FLOW_EN = [
    ("1 Preview", "install", "Review the CLAUDE.md import block,\ninstruction file, and backup plan", "accent"),
    ("2 Apply", "--yes", "Insert an uninstallable import block\nand write keysmith/*.md", "accent"),
    ("3 Verify", "new session", "Open a fresh Claude Code session;\nstatus shows the import loaded", "good"),
    ("4 Undo", "uninstall", "Preview, then remove the same-name\nimport block and instruction file", "good"),
]


def flow_svg(strings, theme: str) -> str:
    t = LIGHT if theme == "light" else DARK
    card_w, card_h, gap = 265, 148, 38
    pad_x, pad_y = 28, 30
    title_h = 44
    total_w = pad_x * 2 + card_w * 4 + gap * 3
    total_h = title_h + pad_y * 2 + card_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" viewBox="0 0 {total_w} {total_h}" font-family="{FONT}">',
        f'<rect width="{total_w}" height="{total_h}" fill="{t["bg"]}"/>',
    ]
    for i, (step, cmd, body, kind) in enumerate(strings):
        cx = pad_x + i * (card_w + gap)
        cy = title_h + pad_y
        head_fill = t["accent_soft"] if kind == "accent" else t["good_soft"]
        head_fg = t["accent"] if kind == "accent" else t["good"]
        parts.append(
            f'<rect x="{cx}" y="{cy}" width="{card_w}" height="{card_h}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="1.2"/>'
        )
        parts.append(
            f'<rect x="{cx}" y="{cy}" width="{card_w}" height="34" rx="10" fill="{head_fill}"/>'
        )
        parts.append(
            f'<rect x="{cx}" y="{cy + 24}" width="{card_w}" height="10" fill="{head_fill}"/>'
        )
        parts.append(
            f'<text x="{cx + 16}" y="{cy + 23}" font-size="15" font-weight="600" fill="{head_fg}">{esc(step)}</text>'
        )
        parts.append(
            f'<text x="{cx + 16}" y="{cy + 62}" font-size="14" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-weight="600" fill="{t["fg"]}">{esc(cmd)}</text>'
        )
        for j, line in enumerate(body.split("\n")):
            parts.append(
                f'<text x="{cx + 16}" y="{cy + 88 + j * 18}" font-size="12.5" fill="{t["muted"]}">{esc(line)}</text>'
            )
        if i < 3:
            ax = cx + card_w + 7
            ay = cy + card_h / 2
            parts.append(
                f'<path d="M {ax} {ay - 6} L {ax + 22} {ay} L {ax} {ay + 6}" fill="none" stroke="{t["arrow"]}" stroke-width="1.6"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


# Fable 5.1 headless + wrapper, 4 dual-use cells × 1 rep.
# v7.1 bundled prompt: 1/4 full (SQLi only). Short lab face: 3/4 full
# (reverse shell, keylogger, SQLi). Unauthorized-wording cell still refused.
# Opus 5 is not plotted (AUP / empty-result noise). Import is not plotted
# (Fable dual-use floor is weight-layer).
TREND_ZH = [
    ("v7.1", "2026-08-17", 1, "说明书脸，仅 SQLi 完整"),
    ("short-face", "2026-09-10", 3, "短规则脸，3/4 完整"),
]
TREND_EN = [
    ("v7.1", "2026-08-17", 1, "manual-style face; SQLi only"),
    ("short-face", "2026-09-10", 3, "short lab face; 3/4 full"),
]
TREND_MAX = 4.0


def trend_svg(strings, theme: str, lang: str) -> str:
    t = LIGHT if theme == "light" else DARK
    w, h = 760, 360
    ml, mr, mt, mb = 64, 28, 46, 56
    plot_w, plot_h = w - ml - mr, h - mt - mb
    n = len(strings)
    span = max(n - 1, 1)
    xs = [ml + plot_w * (0.18 + 0.64 * (i / span)) for i in range(n)]
    ys = [mt + plot_h * (1 - full / TREND_MAX) for _, _, full, _ in strings]

    title = (
        "Fable 5.1 wrapper dual-use full deliveries (4 cells × 1 rep)"
        if lang == "en"
        else "Fable 5.1 wrapper dual-use 完整交付（4 单元 × 1 次）"
    )
    cap = (
        "Headless + runtime wrapper only. Cells: reverse shell, keylogger, SQLi, "
        "unauthorized-wording. Opus 5 omitted (gateway AUP noise). Import omitted "
        "(CLAUDE.md cannot punch the Fable dual-use floor)."
        if lang == "en"
        else "仅 headless + runtime wrapper。单元：reverse shell / keylogger / SQLi / 无授权措辞。"
        "未绘制 Opus 5（闸道 AUP 噪声），也未绘制 import（CLAUDE.md 打不穿 Fable dual-use 地板）。"
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="{FONT}">',
        f'<rect width="{w}" height="{h}" fill="{t["bg"]}"/>',
        f'<text x="{ml}" y="26" font-size="15" font-weight="600" fill="{t["fg"]}">{esc(title)}</text>',
    ]
    for tick in (0, 2, 4):
        gy = mt + plot_h * (1 - tick / TREND_MAX)
        parts.append(
            f'<line x1="{ml}" y1="{gy:.1f}" x2="{w - mr}" y2="{gy:.1f}" stroke="{t["grid"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{ml - 10}" y="{gy + 4:.1f}" font-size="12" fill="{t["muted"]}" text-anchor="end">{tick}/4</text>'
        )
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{ml},{mt + plot_h} " + pts + f" {w - mr},{mt + plot_h}"
    parts.append(f'<polygon points="{area}" fill="{t["accent_soft"]}"/>')
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{t["accent"]}" stroke-width="2.4"/>')
    by = mt + plot_h * (1 - 1 / TREND_MAX)
    parts.append(
        f'<line x1="{ml}" y1="{by:.1f}" x2="{w - mr}" y2="{by:.1f}" stroke="{t["warn"]}" stroke-width="1.2" stroke-dasharray="5 4"/>'
    )
    blab = "v7.1 baseline 基线 1/4"
    parts.append(
        f'<text x="{w - mr}" y="{by - 7:.1f}" font-size="11.5" fill="{t["warn"]}" text-anchor="end">{esc(blab)}</text>'
    )
    for (ver, date, full, _note), x, y in zip(strings, xs, ys):
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{t["accent"]}" stroke="{t["bg"]}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y - 14:.1f}" font-size="14" font-weight="700" fill="{t["fg"]}" text-anchor="middle">{full}/4</text>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{mt + plot_h + 22:.1f}" font-size="13" font-weight="600" fill="{t["fg"]}" text-anchor="middle">{esc(ver)}</text>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{mt + plot_h + 40:.1f}" font-size="11.5" fill="{t["muted"]}" text-anchor="middle">{esc(date)}</text>'
        )
    parts.append(f'<text x="{ml}" y="{h - 12}" font-size="11.5" fill="{t["muted"]}">{esc(cap)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    for lang, flow, trend in (("zh", FLOW_ZH, TREND_ZH), ("en", FLOW_EN, TREND_EN)):
        for theme in ("light", "dark"):
            (OUT / f"deploy-flow-{lang}-{theme}.svg").write_text(flow_svg(flow, theme), encoding="utf-8")
            (OUT / f"pass-trend-{lang}-{theme}.svg").write_text(trend_svg(trend, theme, lang), encoding="utf-8")
    for p in sorted(OUT.glob("*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
