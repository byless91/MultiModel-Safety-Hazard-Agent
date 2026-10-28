"""R4/T10: measure actual HTTP activity, including bypasses and retry paths."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from app.core.config import Settings, get_settings
from app.services.ensemble.analyzer import run_parallel_analysis
from app.services.llm_concurrency import HTTPConcurrencyGate
from app.services.providers import http as provider_http
from app.services.providers.base import ModelCapacityError, ModelTimeoutError, ModelUnavailableError
from app.services.providers.http import OpenAICompatibleProvider
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def gate(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_concurrent_llm_calls", 4)
    monkeypatch.setattr(get_settings(), "llm_queue_timeout_seconds", 2.0)
    monkeypatch.setattr(provider_http, "http_gate", HTTPConcurrencyGate())
    monkeypatch.setattr(provider_http, "record_call", lambda **kwargs: None)


def reply(request):
    if request.url.path.endswith("embeddings"):
        payload = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"embedding": [1.0, 0.0]} for _ in payload["input"]]})
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
        "scene_summary": "测试场景", "hazards": [], "vision_confidence": 0.8,
    })}}]})


def make_provider(handler, *, name="test-real", retries=0):
    return OpenAICompatibleProvider(
        base_url="https://model.invalid/v1", api_key="offline-test", vision_model="vision", text_model="text",
        embedding_model="embed", name=name, transport=httpx.MockTransport(handler), max_retries=retries,
        retry_backoff=0,
    )


class Activity:
    def __init__(self):
        self.condition = threading.Condition()
        self.release = threading.Event()
        self.active = self.peak = self.calls = 0

    def handle(self, request):
        with self.condition:
            self.active += 1
            self.calls += 1
            self.peak = max(self.peak, self.active)
            self.condition.notify_all()
        try:
            assert self.release.wait(4), "test controller did not release transport"
            return reply(request)
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


@pytest.mark.parametrize("mode", ["direct", "single_ensemble", "dual_ensemble", "mixed"])
def test_six_requests_share_four_actual_http_slots(mode):
    activity = Activity()
    providers = [make_provider(activity.handle, name=f"real-{i}") for i in range(2)]
    operations = [
        lambda: providers[0].analyze([], "现场描述"),
        lambda: providers[1].complete("refine", "待细化事实"),
        lambda: providers[0].compare([], [], "整改说明"),
        lambda: providers[1].embed(["依据"] * 11),
    ]

    def call(index):
        if mode == "direct":
            return providers[0].analyze([], "现场描述")
        if mode == "single_ensemble":
            return run_parallel_analysis(providers[:1], [], "现场描述")
        if mode == "dual_ensemble":
            return run_parallel_analysis(providers, [], "现场描述")
        return operations[index % len(operations)]()

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(call, index) for index in range(6)]
            try:
                with activity.condition:
                    assert activity.condition.wait_for(lambda: activity.active == 4, timeout=3)
                    assert activity.peak == 4 and activity.calls == 4
            finally:
                activity.release.set()
            results = [future.result(timeout=4) for future in futures]
        assert activity.active == 0 and activity.peak == 4
        assert activity.calls == (12 if mode == "dual_ensemble" else 7 if mode == "mixed" else 6)
        if "ensemble" in mode:
            assert all(result.failed == 0 for result in results)
    finally:
        for provider in providers:
            provider.close()


@pytest.mark.parametrize("failure", ["timeout", "transport", "http400", "http500", "json", "unexpected"])
def test_all_failure_paths_release_capacity(monkeypatch, failure):
    monkeypatch.setattr(get_settings(), "max_concurrent_llm_calls", 1)
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count > 1:
            return reply(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline timeout", request=request)
        if failure == "transport":
            raise httpx.ConnectError("offline transport", request=request)
        if failure.startswith("http"):
            return httpx.Response(int(failure[4:]), text="offline error")
        if failure == "json":
            return httpx.Response(200, content=b"not json")
        raise RuntimeError("offline unexpected failure")

    provider = make_provider(handler)
    try:
        with pytest.raises((ModelUnavailableError, ModelTimeoutError, ValueError, RuntimeError)):
            provider.complete("refine", "facts")
        assert provider.complete("refine", "facts")["scene_summary"] == "测试场景"
        assert count == 2
    finally:
        provider.close()


@pytest.mark.parametrize("failure", ["timeout", "http429", "http503"])
def test_retry_backoff_holds_no_slot_and_reacquires_for_next_attempt(monkeypatch, failure):
    monkeypatch.setattr(get_settings(), "max_concurrent_llm_calls", 1)
    backoff, retry = threading.Event(), threading.Event()
    attempts = 0

    def handler(request):
        nonlocal attempts
        if request.url.path.endswith("embeddings"):
            return reply(request)
        attempts += 1
        if attempts == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("offline retry", request=request)
            return httpx.Response(int(failure[4:]), headers={"Retry-After": "0"})
        return reply(request)

    provider = make_provider(handler, retries=1)

    def sleep(*args):
        backoff.set()
        assert retry.wait(3)

    monkeypatch.setattr(provider, "_sleep_before_retry", sleep)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(provider.complete, "refine", "facts")
            try:
                assert backoff.wait(2)
                # A different purpose must proceed while the first call backs off.
                assert pool.submit(provider.embed, ["依据"]).result(timeout=1) == [[1.0, 0.0]]
            finally:
                retry.set()
            assert future.result(timeout=2)["scene_summary"] == "测试场景"
        assert attempts == 2
    finally:
        provider.close()


def test_queue_timeout_sends_no_http_and_does_not_retry(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_concurrent_llm_calls", 1)
    monkeypatch.setattr(get_settings(), "llm_queue_timeout_seconds", 0.04)
    activity, ledger = Activity(), []
    monkeypatch.setattr(provider_http, "record_call", lambda **kwargs: ledger.append(kwargs))
    provider = make_provider(activity.handle, retries=3)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(provider.complete, "refine", "facts")
            try:
                with activity.condition:
                    assert activity.condition.wait_for(lambda: activity.active == 1, timeout=2)
                with pytest.raises(ModelCapacityError, match="未发送 HTTP"):
                    provider.embed(["依据"])
                assert activity.calls == 1
                assert ledger[0]["error_type"] == "capacity_timeout"
                assert ledger[0]["retry_count"] == 0
            finally:
                activity.release.set()
            first.result(timeout=2)
        assert provider.embed(["依据"]) == [[1.0, 0.0]]
        assert activity.calls == 2
    finally:
        provider.close()


def test_recursive_http_entry_fails_without_deadlocking(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_concurrent_llm_calls", 1)
    gate = HTTPConcurrencyGate()
    with gate.slot():
        with pytest.raises(ModelUnavailableError, match="递归调用"):
            with gate.slot():
                pytest.fail("nested HTTP slot must not be granted")
    with gate.slot():
        pass


@pytest.mark.parametrize("values", [{"max_concurrent_llm_calls": 0}, {"llm_queue_timeout_seconds": 0}])
def test_invalid_capacity_configuration_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
