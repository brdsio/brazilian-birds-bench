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

import os
import sys
import time

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ENV_TOKEN = "OPENROUTER_API_KEY"

SYSTEM_PROMPT = (
    "You are an ornithology expert. When given a Brazilian Portuguese bird "
    "common name, respond with only its English common name. Do not include "
    "any explanation, punctuation, or additional text."
)

USER_TEMPLATE = "{portuguese_name}"

ESTIMATED_PROMPT_TOKENS = 50


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
    reasoning_effort: str = "none",
) -> dict[str, object]:
    """Call OpenRouter for a single bird name.

    Returns model_response, finish_reason, truncated, latency_ms, and token
    usage fields.  When ``finish_reason`` is ``"length"`` the response was cut
    off before the model finished -- ``truncated`` is ``True``.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(
            portuguese_name=portuguese_name,
        )},
    ]
    actual_effort = reasoning_effort
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "reasoning": {"effort": actual_effort},
    }

    t0 = time.monotonic()
    resp = requests.post(
        OPENROUTER_URL, headers=headers, json=payload, timeout=120,
    )

    # Some models require reasoning — retry with "low" if "none" is rejected.
    if (
        actual_effort == "none"
        and resp.status_code == 400
        and "reasoning" in resp.text.lower()
    ):
        actual_effort = "low"
        payload["reasoning"] = {"effort": actual_effort}
        t0 = time.monotonic()
        resp = requests.post(
            OPENROUTER_URL, headers=headers, json=payload, timeout=120,
        )

    latency_ms = round((time.monotonic() - t0) * 1000)

    resp.raise_for_status()
    data = resp.json()

    choice = data["choices"][0]
    finish = choice.get("finish_reason", "")
    usage = data.get("usage") or {}

    return {
        "model_response": choice["message"]["content"].strip(),
        "finish_reason": finish,
        "truncated": finish == "length",
        "reasoning_effort": actual_effort,
        "latency_ms": latency_ms,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def process_row(
    row: dict[str, object],
    model: str,
    token: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    reasoning_effort: str = "none",
    index: int = 0,
    total: int = 0,
) -> dict[str, object]:
    """Call the LLM for one dataset row, with error handling and progress output.

    Returns the original row merged with model/response/latency/token fields.
    """
    pt_name = row["portuguese_name"]
    label = f"[{index}/{total}] " if total else ""
    print(f"{label}{pt_name} ...", end=" ", file=sys.stderr, flush=True)

    try:
        llm = call_llm(
            pt_name, model, token,
            temperature=temperature, max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
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
            "reasoning_effort": reasoning_effort,
            "latency_ms": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": error_msg,
        }
    except Exception as exc:
        llm = {
            "model_response": "",
            "finish_reason": "error",
            "truncated": False,
            "reasoning_effort": reasoning_effort,
            "latency_ms": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": str(exc),
        }

    tag = ""
    if llm.get("truncated"):
        tag = " [TRUNCATED]"
    elif llm.get("finish_reason") == "error":
        tag = f" [ERROR: {llm.get('error', 'unknown')}]"
    print(
        f"{llm.get('model_response', '')}{tag}  ({llm.get('latency_ms', 0)}ms)",
        file=sys.stderr,
    )

    return {**row, "model": model, **llm}
