"""R6/T17: actual HTTP attempts, returned model IDs and unknown costs stay visible."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import httpx
import pytest
from app.eval.contracts import call_statistics, load_experiment_file
from app.services.llm_observation import observe_calls
from app.services.providers.http import OpenAICompatibleProvider


def test_real_provider_transport_records_attempts_and_exact_served_model(monkeypatch, tmp_path):
    attempts = []

    def transport(request):
        attempts.append(json.loads(request.content))
        if len(attempts) == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "model": "vendor/model-2026-build.17",
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
                "choices": [
                    {
                        "message": {
                            "content": '{"scene_summary":"现场","hazards":[],"hazard_hints":[],"vision_confidence":0.8}'
                        }
                    }
                ],
            },
        )

    monkeypatch.setattr("app.services.providers.http.record_call", lambda **kwargs: None)
    provider = OpenAICompatibleProvider(
        base_url="https://provider.invalid/v1",
        api_key="fake-only",
        vision_model="alias",
        text_model="text",
        embedding_model="embed",
        retry_backoff=0,
        transport=httpx.MockTransport(transport),
    )
    from app.services.providers.base import ImageInput
    from PIL import Image

    path = tmp_path / "photo.png"
    Image.new("RGB", (8, 8), "red").save(path)
    with observe_calls() as outer:
        with observe_calls() as inner:
            result = provider.analyze([ImageInput(filename="photo.png", path=path, mime_type="image/png")], "现场")
    provider.close()
    assert result["response_model"] == "vendor/model-2026-build.17"
    assert len(inner.events) == len(outer.events) == 2
    import base64

    image_url = attempts[1]["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1]) == path.read_bytes()
    stats = call_statistics(outer.events)
    assert stats["http_attempt_count"] == 2 and stats["http_error_count"] == 1
    assert stats["response_model_identifiers"] == ["vendor/model-2026-build.17"]
    assert stats["estimated_cost"] is None and stats["unpriced_attempt_count"] == 2
    priced = call_statistics(
        [outer.events[1]],
        {
            "currency": "TEST",
            "models": {"vendor/model-2026-build.17": {"input_per_million": 1, "output_per_million": 2}},
        },
    )
    assert priced["estimated_cost"] == pytest.approx(0.00003)
    assert priced["cost_status"] == "estimated"


def test_parallel_observers_propagate_without_cross_batch_leaks():
    from app.services.llm_observation import record_observation

    with ThreadPoolExecutor(2) as pool, observe_calls() as observation:
        futures = [pool.submit(copy_context().run, record_observation, status="success", index=i) for i in range(8)]
        for future in futures:
            future.result()
    assert sorted(event["index"] for event in observation.events) == list(range(8))
    with observe_calls() as next_batch:
        pass
    assert next_batch.events == []


def test_invalid_pricing_rejected_before_any_model_calls(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text(
        json.dumps({"currency": "CNY", "models": {"m": {"input_per_million": -1, "output_per_million": 0}}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-negative"):
        load_experiment_file(path, pricing=True)


@pytest.mark.parametrize("invalid", ["20", -1, True, None])
def test_invalid_or_missing_usage_is_unknown_cost(invalid):
    stats = call_statistics([{"status": "success", "requested_model": "alias", "response_model": "served",
                              "latency_ms": 2, "tokens_in": invalid, "tokens_out": 1}],
                            {"currency": "TEST", "models": {"served": {
                                "input_per_million": 1, "output_per_million": 1}}})
    assert stats["estimated_cost"] is None
    assert stats["usage_missing_count"] == 1
