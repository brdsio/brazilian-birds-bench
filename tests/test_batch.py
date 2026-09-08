import json

import pytest
from click.testing import CliRunner

from src.batch import (
    base_model,
    batch_custom_id,
    batch_variant,
    build_request_body,
    parse_batch_result,
)
from src.cli import cli


def test_batch_slug_is_distinct_from_base_model():
    assert batch_variant("anthropic/claude-fable-5.1") == (
        "anthropic/claude-fable-5.1:batch"
    )
    assert base_model("anthropic/claude-fable-5.1:batch") == (
        "anthropic/claude-fable-5.1"
    )


def test_batch_custom_id_obeys_provider_character_restrictions():
    assert batch_custom_id("CBRO#0004") == "CBRO_0004"


def test_batch_request_preserves_benchmark_protocol():
    body = build_request_body(
        "ema", "anthropic/claude-fable-5.1",
        temperature=0.0, max_tokens=2048,
        reasoning_config={"effort": "low"}, provider_config=None,
    )
    assert body["model"] == "anthropic/claude-fable-5.1"
    assert body["messages"][1] == {"role": "user", "content": "ema"}
    assert body["temperature"] == 0.0
    assert body["reasoning"] == {"effort": "low"}


def test_parse_successful_batch_result():
    item = {
        "custom_id": "CBRO#0004",
        "response": {
            "status_code": 200,
            "request_id": "req-1",
            "body": {
                "id": "gen-1",
                "model": "anthropic/claude-fable-5.1",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": "Greater Rhea"},
                }],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 3,
                    "total_tokens": 23,
                },
            },
        },
    }
    parsed = parse_batch_result(
        item, reasoning_config={"effort": "low"}, benchmark_mode="reasoning",
    )
    assert parsed["model_response"] == "Greater Rhea"
    assert parsed["resolved_model"] == "anthropic/claude-fable-5.1"
    assert parsed["finish_reason"] == "stop"
    assert parsed["total_tokens"] == 23


@pytest.mark.parametrize("status_code", [400, 429, 500])
def test_parse_failed_batch_result(status_code):
    parsed = parse_batch_result(
        {
            "custom_id": "CBRO#0004",
            "response": {"status_code": status_code, "body": {}},
            "error": {"message": "failed"},
        },
        reasoning_config={"effort": "low"}, benchmark_mode="reasoning",
    )
    assert parsed["finish_reason"] == "error"
    assert json.loads(parsed["error"])["message"] == "failed"


def test_batch_run_dry_run_uses_fable_defaults(monkeypatch):
    monkeypatch.setattr(
        "src.batch.validate_batch_model",
        lambda model, token=None: {
            "canonical_slug": "anthropic/claude-fable-5.1-20260831"
        },
    )
    result = CliRunner().invoke(
        cli,
        [
            "batch-run", "--model", "anthropic/claude-fable-5.1",
            "--benchmark-mode", "reasoning", "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "10 × up to 200" in result.output
    assert "Max tokens:     512" in result.output


def test_batch_run_dry_run_uses_gemini_flash_defaults(monkeypatch):
    monkeypatch.setattr(
        "src.batch.validate_batch_model",
        lambda model, token=None: {
            "canonical_slug": "google/gemini-3.8-flash-20260902"
        },
    )
    result = CliRunner().invoke(
        cli,
        [
            "batch-run",
            "--model",
            "google/gemini-3.8-flash",
            "--benchmark-mode",
            "reasoning",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "10 × up to 200" in result.output
    assert "Max tokens:     2048" in result.output
    assert "Reasoning cfg:  {'effort': 'low'}" in result.output


def test_batch_status_accepts_batch_run_state(monkeypatch, tmp_path):
    state_path = tmp_path / "run.batch-run.json"
    state_path.write_text(
        json.dumps({
            "active_batch_id": "batch-1",
            "active_cbro_ids": ["CBRO#0004", "CBRO#0011"],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.batch.get_batch",
        lambda batch_id, token: {
            "id": batch_id, "status": "in_progress", "results": [],
        },
    )
    monkeypatch.setattr("src.runner.get_openrouter_token", lambda token: "token")

    result = CliRunner().invoke(cli, ["batch-status", "--state", str(state_path)])

    assert result.exit_code == 0, result.output
    assert "Batch batch-1: in_progress (0/2 results)" in result.output


def test_batch_status_rejects_completed_batch_run_without_active_id(tmp_path):
    state_path = tmp_path / "completed.batch-run.json"
    state_path.write_text(
        json.dumps({
            "batch_status": "completed",
            "completed_count": 1836,
            "active_batch_id": "",
        }),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["batch-status", "--state", str(state_path)])

    assert result.exit_code != 0
    assert "No active batch ID found" in result.output
