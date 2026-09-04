# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib>=3.9"]
# ///
"""Generate publication charts from the versioned benchmark result CSVs."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUTPUT = ROOT / "assets" / "charts"

MODELS = [
    ("GPT-5.6", None, "openai--gpt-5.6-sol_reasoning_batch.csv"),
    ("GPT-5.5", "openai--gpt-5.5_no_reasoning.csv", "openai--gpt-5.5_reasoning.csv"),
    (
        "Claude Opus 4.8",
        "anthropic--claude-opus-4.8_no_reasoning.csv",
        "anthropic--claude-opus-4.8_reasoning.csv",
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


def leaderboard() -> None:
    labels = [model[0] for model in MODELS][::-1]
    values = [accuracy(model[2]) for model in MODELS][::-1]
    colors = [GOLD if label == "GPT-5.6" else TEAL for label in labels]

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
        "Fonte: Brazilian Birds Bench v1.1.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    ax.tick_params(colors=INK, labelsize=10, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    finish(fig, "reasoning_leaderboard_v1_1")


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
        "Fonte: Brazilian Birds Bench v1.1.",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    ax.legend(frameon=False, loc="lower right", labelcolor=INK)
    ax.tick_params(colors=INK, labelsize=10, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    finish(fig, "reasoning_comparison_v1_1")


if __name__ == "__main__":
    leaderboard()
    reasoning_comparison()
