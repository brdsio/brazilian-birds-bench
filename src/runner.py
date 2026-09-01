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

import json
import os
import sys
import time
from datetime import UTC, datetime

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
    reasoning_config: dict[str, object] | None = None,
    provider_config: dict[str, object] | None = None,
    benchmark_mode: str = "",
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
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_config is not None:
        payload["reasoning"] = reasoning_config
    if provider_config is not None:
        payload["provider"] = provider_config

    t0 = time.monotonic()
    resp = requests.post(
        OPENROUTER_URL, headers=headers, json=payload, timeout=120,
    )

    latency_ms = round((time.monotonic() - t0) * 1000)

    if resp.status_code != 200:
        body = resp.text[:500]
        raise requests.HTTPError(
            f"OpenRouter {resp.status_code} for model={model} "
            f"reasoning={reasoning_config!r}: {body}",
            response=resp,
        )

    data = resp.json()

    choice = data["choices"][0]
    finish = choice.get("finish_reason", "")
    usage = data.get("usage") or {}

    # ``content`` is ``None`` when the model spent its entire token budget on
    # reasoning and never emitted an answer (``finish_reason == "length"``).
    # Coerce to "" so we report it as truncated instead of crashing on
    # ``None.strip()``.  Lower the reasoning effort to avoid this.
    content = choice["message"].get("content") or ""

    return {
        "model_response": content.strip(),
        "finish_reason": finish,
        "truncated": finish == "length",
        "reasoning_config": json.dumps(reasoning_config) if reasoning_config else "",
        "effective_reasoning_config": (
            "accepted_not_echoed_by_api:"
            + (json.dumps(reasoning_config) if reasoning_config else "omitted")
        ),
        "benchmark_mode": benchmark_mode,
        "resolved_model": data.get("model", ""),
        "generation_id": data.get("id", ""),
        "request_id": resp.headers.get("x-request-id", ""),
        "provider": data.get("provider", ""),
        "response_created": data.get("created", ""),
        "requested_at_utc": datetime.now(UTC).isoformat(),
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
    reasoning_config: dict[str, object] | None = None,
    provider_config: dict[str, object] | None = None,
    benchmark_mode: str = "",
    index: int = 0,
    total: int = 0,
    score_fn: object = None,
    run_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Call the LLM for one dataset row, with error handling and progress output.

    Returns the original row merged with model/response/latency/token fields.
    If *score_fn* is provided it is called on the merged row and the scored
    result is returned instead (and a hit/miss indicator is printed).
    """
    pt_name = row["portuguese_name"]
    label = f"[{index}/{total}] " if total else ""
    print(f"{label}{pt_name} ...", end=" ", file=sys.stderr, flush=True)

    rc_serialized = json.dumps(reasoning_config) if reasoning_config else ""
    run_metadata = run_metadata or {}

    try:
        llm = call_llm(
            pt_name, model, token,
            temperature=temperature, max_tokens=max_tokens,
            reasoning_config=reasoning_config,
            provider_config=provider_config,
            benchmark_mode=benchmark_mode,
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
            "reasoning_config": rc_serialized,
            "effective_reasoning_config": "unknown_request_failed",
            "benchmark_mode": benchmark_mode,
            "resolved_model": "",
            "generation_id": "",
            "request_id": "",
            "provider": "",
            "response_created": "",
            "requested_at_utc": datetime.now(UTC).isoformat(),
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
            "reasoning_config": rc_serialized,
            "effective_reasoning_config": "unknown_request_failed",
            "benchmark_mode": benchmark_mode,
            "resolved_model": "",
            "generation_id": "",
            "request_id": "",
            "provider": "",
            "response_created": "",
            "requested_at_utc": datetime.now(UTC).isoformat(),
            "latency_ms": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error": str(exc),
        }

    merged = {**row, "model": model, **run_metadata, **llm}

    tag = ""
    if llm.get("truncated"):
        tag = " [TRUNCATED]"
    elif llm.get("finish_reason") == "error":
        tag = f" [ERROR: {llm.get('error', 'unknown')}]"

    if score_fn is not None:
        scored = score_fn(merged)
        if not tag:
            if scored.get("acceptable_match") in (True, "True"):
                tag = " ✓"
            else:
                tag = " ✗"
        print(
            f"{llm.get('model_response', '')}{tag}  ({llm.get('latency_ms', 0)}ms)",
            file=sys.stderr,
        )
        return scored

    print(
        f"{llm.get('model_response', '')}{tag}  ({llm.get('latency_ms', 0)}ms)",
        file=sys.stderr,
    )
    return merged
