# /// script
# requires-python = ">=3.12"
# dependencies = ["cairosvg>=2.7", "matplotlib>=3.9"]
# ///
"""Generate publication charts from the versioned benchmark result CSVs."""

from __future__ import annotations

import csv
import sys
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import cairosvg
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUTPUT = ROOT / "assets" / "charts"

MODELS = [
    ("GPT-6 Astra", None, "openai--gpt-6-astra_reasoning_batch.csv"),
    ("GPT-5.6", None, "openai--gpt-5.6-sol_reasoning_batch.csv"),
    ("GPT-5.5", "openai--gpt-5.5_no_reasoning.csv", "openai--gpt-5.5_reasoning.csv"),
    (
        "Claude Opus 4.8",
        "anthropic--claude-opus-4.8_no_reasoning.csv",
        "anthropic--claude-opus-4.8_reasoning.csv",
    ),
    (
        "Gemini 3.8 Flash",
        None,
        "google--gemini-3.8-flash_reasoning_batch.csv",
    ),
    (
        "Gemini 3.1 Flash Lite",
        "google--gemini-3.1-flash-lite_no_reasoning.csv",
        "google--gemini-3.1-flash-lite_reasoning.csv",
    ),
    ("Claude Fable 5.1", None, "anthropic--claude-fable-5.1_reasoning_batch.csv"),
    (
        "DeepSeek V4 Pro",
        "deepseek--deepseek-v4-pro_no_reasoning.csv",
        "deepseek--deepseek-v4-pro_reasoning.csv",
    ),
    (
        "Claude Sonnet 4.6",
        "anthropic--claude-sonnet-4.6_no_reasoning.csv",
        "anthropic--claude-sonnet-4.6_reasoning.csv",
    ),
    (
        "GPT-5.4 mini",
        "openai--gpt-5.4-mini_no_reasoning.csv",
        "openai--gpt-5.4-mini_reasoning.csv",
    ),
    (
        "Qwen 3.7 Plus*",
        "qwen--qwen3.7-plus_no_reasoning.csv",
        "qwen--qwen3.7-plus_reasoning.csv",
    ),
    (
        "Kimi K2.6",
        "moonshotai--kimi-k2.6_no_reasoning.csv",
        "moonshotai--kimi-k2.6_reasoning.csv",
    ),
    (
        "Mistral Small",
        "mistralai--mistral-small-2603_no_reasoning.csv",
        "mistralai--mistral-small-2603_reasoning.csv",
    ),
]

INK = "#17324D"
TEAL = "#168C83"
GOLD = "#F2B134"
GRID = "#DCE5E8"
MUTED = "#66757F"
BACKGROUND = "#FAFCFC"

LABS = {
    "OpenAI": ("#10A37F", "openai"),
    "Anthropic": ("#D97757", "anthropic"),
    "Google": ("#4285F4", "google"),
    "DeepSeek": ("#4D6BFE", "deepseek"),
    "Qwen": ("#6554C0", "qwen"),
    "Moonshot AI": ("#252A34", "kimi"),
    "Mistral AI": ("#F26B38", "mistralai"),
}

MODEL_LABS = {
    "GPT-6 Astra": "OpenAI",
    "GPT-5.6": "OpenAI",
    "GPT-5.5": "OpenAI",
    "Claude Opus 4.8": "Anthropic",
    "Gemini 3.8 Flash": "Google",
    "Gemini 3.1 Flash Lite": "Google",
    "Claude Fable 5.1": "Anthropic",
    "DeepSeek V4 Pro": "DeepSeek",
    "Claude Sonnet 4.6": "Anthropic",
    "GPT-5.4 mini": "OpenAI",
    "Qwen 3.7 Plus*": "Qwen",
    "Kimi K2.6": "Moonshot AI",
    "Mistral Small": "Mistral AI",
}

csv.field_size_limit(sys.maxsize)


def accuracy(filename: str) -> float:
    with (RESULTS / filename).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return sum(row["acceptable_match"].lower() == "true" for row in rows) / len(rows)


def finish(fig: plt.Figure, stem: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / f"{stem}.svg", bbox_inches="tight", facecolor=BACKGROUND)
    fig.savefig(
        OUTPUT / f"{stem}.png",
        dpi=200,
        bbox_inches="tight",
        facecolor=BACKGROUND,
    )
    plt.close(fig)


def lab_icon(slug: str, color: str):
    """Load a monochrome Simple Icons mark and return it as image data."""
    url = f"https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/{slug}.svg"
    with urlopen(url, timeout=30) as response:
        svg = response.read().decode("utf-8")
    svg = svg.replace("<svg ", f'<svg fill="{color}" ', 1)
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=96, output_height=96)
    return plt.imread(BytesIO(png), format="png")


def vertical_brand_leaderboard() -> None:
    """Create the English, brand-colored chart intended for the blog post."""
    labels = [model[0] for model in MODELS]
    values = [accuracy(model[2]) for model in MODELS]
    labs = [MODEL_LABS[label] for label in labels]

    fig, ax = plt.subplots(figsize=(16, 9))
    fig.subplots_adjust(left=0.06, right=0.98, top=0.83, bottom=0.34)
    fig.patch.set_facecolor(BACKGROUND)
    ax.set_facecolor(BACKGROUND)

    bar_width = 0.72
    for x, (label, value, lab) in enumerate(zip(labels, values, labs, strict=True)):
        color, slug = LABS[lab]
        bar = FancyBboxPatch(
            (x - bar_width / 2, 0),
            bar_width,
            value,
            boxstyle="round,pad=0,rounding_size=0.055",
            linewidth=0,
            facecolor=color,
            zorder=3,
        )
        ax.add_patch(bar)
        ax.text(
            x,
            value - 0.035,
            f"{value:.2%}",
            ha="center",
            va="top",
            color="white",
            fontsize=11,
            fontweight="bold",
            zorder=4,
        )
        try:
            icon = OffsetImage(lab_icon(slug, color), zoom=0.27)
            ax.add_artist(
                AnnotationBbox(
                    icon,
                    (x, -0.075),
                    xycoords=("data", "axes fraction"),
                    frameon=False,
                    box_alignment=(0.5, 0.5),
                )
            )
        except OSError:
            ax.text(
                x,
                -0.075,
                lab[0],
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="center",
                color=color,
                fontsize=16,
                fontweight="bold",
            )
        ax.text(
            x,
            -0.145,
            label,
            transform=ax.get_xaxis_transform(),
            rotation=52,
            ha="right",
            va="top",
            color=INK,
            fontsize=10,
            fontweight="semibold",
        )

    ax.set_xlim(-0.7, len(labels) - 0.3)
    ax.set_ylim(0, 0.9)
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8])
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_xticks([])
    ax.set_title(
        "How well do AI models know Brazilian birds?",
        loc="left",
        color=INK,
        fontsize=27,
        fontweight="bold",
        pad=32,
    )
    ax.text(
        0,
        1.035,
        "Acceptable-match accuracy with reasoning · 1,836 species",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=13,
    )
    ax.text(
        0,
        -0.56,
        "* Qwen reasoning run is partial (655 species). "
        "Source: Brazilian Birds Bench v1.2.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=10,
    )
    ax.tick_params(axis="y", colors=MUTED, labelsize=10, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    finish(fig, "vertical_brand_leaderboard_v1_2")


def leaderboard() -> None:
    labels = [model[0] for model in MODELS][::-1]
    values = [accuracy(model[2]) for model in MODELS][::-1]
    colors = [GOLD if label == "GPT-6 Astra" else TEAL for label in labels]

    fig, ax = plt.subplots(figsize=(10, 7), layout="constrained")
    fig.patch.set_facecolor(BACKGROUND)
    ax.set_facecolor(BACKGROUND)
    bars = ax.barh(labels, values, color=colors, height=0.68)
    ax.bar_label(
        bars,
        labels=[f"{value:.2%}" for value in values],
        padding=7,
        color=INK,
        fontsize=10,
        fontweight="bold",
    )
    ax.set_xlim(0, 0.86)
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(
        "Quanto os modelos conhecem as aves brasileiras?",
        loc="left",
        color=INK,
        fontsize=20,
        fontweight="bold",
        pad=20,
    )
    ax.text(
        0,
        1.015,
        "Acurácia com reasoning · 1.836 espécies",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=11,
    )
    ax.text(
        0,
        -0.12,
        "* Qwen: rodada parcial (655 espécies). Métrica: acceptable match. "
        "Fonte: Brazilian Birds Bench v1.2.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    ax.tick_params(colors=INK, labelsize=10, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    finish(fig, "reasoning_leaderboard_v1_2")


def reasoning_comparison() -> None:
    paired = [
        (label, no_reasoning, reasoning)
        for label, no_reasoning, reasoning in MODELS
        if no_reasoning
    ]
    labels = [item[0] for item in paired][::-1]
    without = [accuracy(item[1]) for item in paired][::-1]
    with_reasoning = [accuracy(item[2]) for item in paired][::-1]
    y = list(range(len(labels)))

    fig, ax = plt.subplots(figsize=(10, 6.5), layout="constrained")
    fig.patch.set_facecolor(BACKGROUND)
    ax.set_facecolor(BACKGROUND)
    without_bars = ax.barh(
        [i - 0.18 for i in y],
        without,
        height=0.32,
        color="#A9BAC2",
        label="Sem reasoning",
    )
    bars = ax.barh(
        [i + 0.18 for i in y],
        with_reasoning,
        height=0.32,
        color=TEAL,
        label="Com reasoning",
    )
    ax.bar_label(
        without_bars,
        labels=[f"{value:.1%}" for value in without],
        padding=5,
        color=MUTED,
        fontsize=9,
    )
    ax.bar_label(
        bars,
        labels=[f"{value:.1%}" for value in with_reasoning],
        padding=5,
        color=INK,
        fontsize=9,
    )
    ax.set_yticks(y, labels)
    ax.set_xlim(0, 0.82)
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(
        "Reasoning melhora a lembrança dos nomes",
        loc="left",
        color=INK,
        fontsize=20,
        fontweight="bold",
        pad=20,
    )
    ax.text(
        0,
        1.02,
        "Acurácia por condição · modelos com as duas rodadas",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=11,
    )
    ax.text(
        0,
        -0.14,
        "* Qwen: rodada com reasoning parcial (655 espécies). "
        "Fonte: Brazilian Birds Bench v1.2.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    ax.legend(frameon=False, loc="lower right", labelcolor=INK)
    ax.tick_params(colors=INK, labelsize=10, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    finish(fig, "reasoning_comparison_v1_2")


if __name__ == "__main__":
    leaderboard()
    reasoning_comparison()
    vertical_brand_leaderboard()
