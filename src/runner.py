"""Run the benchmark: call an LLM via OpenRouter for each species in the dataset.

OpenRouter exposes an OpenAI-compatible chat-completions endpoint, so any model
available there (GPT, Claude, Gemini, Llama, Mistral, ...) can be tested with a
single ``--model`` flag.  No extra SDK is needed -- plain ``requests`` suffices.

The prompt is zero-shot and fixed: a system message that constrains the output
format, and a user message containing only the Portuguese bird name.  This is
intentional -- the benchmark measures what the model *already knows*, not how
well we can coax it with examples or chain-of-thought.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ENV_TOKEN = "OPENROUTER_API_KEY"

SYSTEM_PROMPT = (
    "You are an ornithology expert. When given a Brazilian Portuguese bird "
    "common name, respond with only its English common name. Do not include "
    "any explanation, punctuation, or additional text."
)

USER_TEMPLATE = "{portuguese_name}"


def get_openrouter_token(explicit: str | None = None) -> str:
    """Resolve the OpenRouter API key: explicit arg > .env > environment."""
    if explicit:
        return explicit
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    token = os.environ.get(ENV_TOKEN)
    if not token:
        raise RuntimeError(
            f"OpenRouter API key missing. Set {ENV_TOKEN} in a .env file or "
            f"the environment, or pass --token."
        )
    return token


def call_llm(
    portuguese_name: str,
    model: str,
    token: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> dict[str, object]:
    """Call OpenRouter for a single bird name.

    Returns ``{"model_response": str, "finish_reason": str, "truncated": bool}``.
    When ``finish_reason`` is ``"length"`` the response was cut off before the
    model finished -- ``truncated`` is set to ``True`` so the scorer and the
    summary can flag it.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(
                portuguese_name=portuguese_name,
            )},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(
        OPENROUTER_URL, headers=headers, json=payload, timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    choice = data["choices"][0]
    finish = choice.get("finish_reason", "")
    return {
        "model_response": choice["message"]["content"].strip(),
        "finish_reason": finish,
        "truncated": finish == "length",
    }


def run_benchmark(
    dataset_path: Path,
    model: str,
    token: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> list[dict[str, object]]:
    """Run the benchmark on every row in *dataset_path*.

    Returns a list of dicts: the original dataset columns plus
    ``model``, ``model_response``, ``finish_reason``, and ``truncated``.
    """
    with open(dataset_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    results: list[dict[str, object]] = []
    total = len(rows)

    for i, row in enumerate(rows, 1):
        pt_name = row["portuguese_name"]
        print(f"[{i}/{total}] {pt_name} ...", end=" ", file=sys.stderr, flush=True)

        try:
            llm = call_llm(
                pt_name, model, token,
                temperature=temperature, max_tokens=max_tokens,
            )
        except requests.HTTPError as exc:
            body = ""
            if exc.response is not None:
                try:
                    body = exc.response.json().get("error", {}).get("message", "")
                except Exception:
                    body = exc.response.text[:200]
            error_msg = f"{exc}{f' -- {body}' if body else ''}"
            llm = {
                "model_response": "",
                "finish_reason": "error",
                "truncated": False,
                "error": error_msg,
            }
        except Exception as exc:
            llm = {
                "model_response": "",
                "finish_reason": "error",
                "truncated": False,
                "error": str(exc),
            }

        result = {**row, "model": model, **llm}
        results.append(result)

        tag = ""
        if llm.get("truncated"):
            tag = " [TRUNCATED]"
        elif llm.get("finish_reason") == "error":
            tag = f" [ERROR: {llm.get('error', 'unknown')}]"
        print(f"{llm.get('model_response', '')}{tag}", file=sys.stderr)

    return results
