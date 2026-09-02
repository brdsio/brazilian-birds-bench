"""OpenRouter Batch API support for asynchronous benchmark execution."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import requests

from .runner import SYSTEM_PROMPT, USER_TEMPLATE

BATCHES_URL = "https://openrouter.ai/api/beta/batches"
MODEL_URL = "https://openrouter.ai/api/v1/model"
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}
_INVALID_CUSTOM_ID = re.compile(r"[^A-Za-z0-9_-]")


def batch_variant(model: str) -> str:
    """Return the catalog slug used to verify discounted batch availability."""
    return model if model.endswith(":batch") else f"{model}:batch"


def base_model(model: str) -> str:
    """Strip the catalog-only batch suffix used by the Batch API page."""
    return model.removesuffix(":batch")


def batch_custom_id(cbro_id: str) -> str:
    """Encode a benchmark ID for providers that restrict batch custom IDs."""
    return _INVALID_CUSTOM_ID.sub("_", cbro_id)


def _raise_api_error(response: requests.Response) -> None:
    """Raise an HTTP error containing OpenRouter's useful validation message."""
    if response.ok:
        return
    try:
        message = response.json().get("error", {}).get("message", response.text)
    except ValueError:
        message = response.text
    error = requests.HTTPError(
        f"OpenRouter {response.status_code}: {message[:1000]}", response=response,
    )
    raise error


def validate_batch_model(model: str, token: str | None = None) -> dict[str, Any]:
    """Fail unless OpenRouter currently advertises a batch variant."""
    slug = batch_variant(model)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(
        f"{MODEL_URL}/{quote(slug, safe='/.:')}", headers=headers, timeout=30,
    )
    if response.status_code == 404:
        raise ValueError(
            f"OpenRouter does not currently offer {slug}. Refusing to substitute "
            "a different model version."
        )
    _raise_api_error(response)
    return response.json()["data"]


def build_request_body(
    portuguese_name: str,
    model: str,
    *,
    temperature: float,
    max_tokens: int,
    reasoning_config: dict[str, object] | None,
    provider_config: dict[str, object] | None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "model": base_model(model),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_TEMPLATE.format(portuguese_name=portuguese_name),
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_config is not None:
        body["reasoning"] = reasoning_config
    if provider_config is not None:
        body["provider"] = provider_config
    return body


def submit_batch(
    rows: list[dict[str, str]],
    model: str,
    token: str,
    *,
    temperature: float,
    max_tokens: int,
    reasoning_config: dict[str, object] | None,
    provider_config: dict[str, object] | None,
) -> dict[str, Any]:
    """Submit one independent chat-completion request per benchmark row."""
    model_id = base_model(model)
    requests_payload = [
        {
            "custom_id": batch_custom_id(row["cbro_id"]),
            "body": build_request_body(
                row["portuguese_name"], model_id,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_config=reasoning_config,
                provider_config=provider_config,
            ),
        }
        for row in rows
    ]
    response = requests.post(
        BATCHES_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "endpoint": "/v1/chat/completions",
            "model": model_id,
            "requests": requests_payload,
        },
        timeout=180,
    )
    _raise_api_error(response)
    payload = response.json()
    return payload.get("data", payload)


def get_batch(batch_id: str, token: str) -> dict[str, Any]:
    response: requests.Response | None = None
    # A newly-created batch can briefly return 404 while it propagates from
    # the submission service to the status service.
    for attempt in range(4):
        response = requests.get(
            f"{BATCHES_URL}/{batch_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        if response.status_code != 404 or attempt == 3:
            break
        time.sleep(2)
    assert response is not None
    _raise_api_error(response)
    payload = response.json()
    return payload.get("data", payload)


def wait_for_batch(
    batch_id: str, token: str, *, poll_seconds: int = 30,
) -> dict[str, Any]:
    while True:
        batch = get_batch(batch_id, token)
        if batch.get("status") in TERMINAL_STATUSES:
            return batch
        time.sleep(poll_seconds)


def parse_batch_result(
    item: dict[str, Any],
    *,
    reasoning_config: dict[str, object] | None,
    benchmark_mode: str,
) -> dict[str, object]:
    """Convert an OpenAI-style inlined batch item to runner result fields."""
    wrapped_response = item.get("response") or {}
    status_code = wrapped_response.get("status_code", 200)
    data = wrapped_response.get("body", wrapped_response)
    error = item.get("error") or data.get("error")
    requested_at = datetime.now(UTC).isoformat()
    serialized_reasoning = (
        json.dumps(reasoning_config) if reasoning_config else ""
    )
    if error or status_code >= 400:
        return {
            "model_response": "", "finish_reason": "error",
            "truncated": False, "reasoning_config": serialized_reasoning,
            "effective_reasoning_config": "unknown_request_failed",
            "benchmark_mode": benchmark_mode, "resolved_model": "",
            "generation_id": "", "request_id": wrapped_response.get("request_id", ""),
            "provider": "", "response_created": "",
            "requested_at_utc": requested_at, "latency_ms": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "error": json.dumps(error or {"status_code": status_code}),
        }

    choice = data["choices"][0]
    finish = choice.get("finish_reason", "")
    content = choice.get("message", {}).get("content") or ""
    usage = data.get("usage") or {}
    return {
        "model_response": content.strip(), "finish_reason": finish,
        "truncated": finish == "length", "reasoning_config": serialized_reasoning,
        "effective_reasoning_config": "accepted_not_echoed_by_api:"
        + (serialized_reasoning or "omitted"),
        "benchmark_mode": benchmark_mode, "resolved_model": data.get("model", ""),
        "generation_id": data.get("id", ""),
        "request_id": wrapped_response.get("request_id", ""),
        "provider": data.get("provider", ""),
        "response_created": data.get("created", ""),
        "requested_at_utc": requested_at, "latency_ms": 0,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0), "error": "",
    }
