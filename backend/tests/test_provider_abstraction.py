import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services import providers as provider_pkg
from app.services.providers import (
    ModelTimeoutError,
    ModelUnavailableError,
    OpenAICompatibleProvider,
    build_provider,
    build_providers,
)


def test_mock_fallback_without_keys():
    settings = Settings(provider_mode="auto", dashscope_api_key="", zhipu_api_key="", _env_file=None)
    providers = build_providers(settings)
    assert len(providers) == 1
    assert providers[0].name == "mock"
    assert build_provider(settings).name == "mock"


def test_explicit_mock_mode_ignores_keys():
    settings = Settings(
        provider_mode="mock",
        dashscope_api_key="sk-test",
        zhipu_api_key="secret",
        _env_file=None,
    )
    providers = build_providers(settings)
    assert [item.name for item in providers] == ["mock"]


def test_dashscope_only_creates_qwen_provider():
    settings = Settings(
        provider_mode="auto",
        dashscope_api_key="sk-test",
        zhipu_api_key="",
        vision_model="qwen-vl-plus",
        _env_file=None,
    )
    providers = build_providers(settings)
    assert len(providers) == 1
    assert providers[0].name == "dashscope"
    assert providers[0].family == "qwen-vl"
    assert providers[0].vision_model == "qwen-vl-plus"


def test_zhipu_only_creates_glm_provider_with_own_models():
    settings = Settings(
        provider_mode="auto",
        dashscope_api_key="",
        zhipu_api_key="secret",
        _env_file=None,
    )
    providers = build_providers(settings)
    assert len(providers) == 1
    assert providers[0].name == "zhipu"
    assert providers[0].family == "glm-v"
    assert providers[0].vision_model == "glm-4v-flash"
    assert providers[0].text_model == "glm-4-flash"
    assert providers[0].embedding_model == "embedding-2"


def test_both_keys_create_two_independent_providers():
    settings = Settings(
        provider_mode="auto",
        dashscope_api_key="sk-test",
        zhipu_api_key="secret",
        _env_file=None,
    )
    providers = build_providers(settings)
    assert [item.family for item in providers] == ["qwen-vl", "glm-v"]
    assert [item.name for item in providers] == ["dashscope", "zhipu"]
    # Primary stays the first configured provider for backward compatibility.
    assert build_provider(settings).name == "dashscope"


def test_describe_never_exposes_api_key():
    settings = Settings(
        provider_mode="auto",
        dashscope_api_key="sk-test",
        zhipu_api_key="secret",
        _env_file=None,
    )
    for provider in build_providers(settings):
        info = provider.describe()
        joined = " ".join(info.values())
        assert "api_key" not in info
        assert "sk-test" not in joined
        assert "secret" not in joined


def test_get_provider_uses_runtime_settings(monkeypatch):
    def fake_settings():
        return Settings(provider_mode="mock", _env_file=None)

    monkeypatch.setattr(provider_pkg, "get_settings", fake_settings)
    provider_pkg.reset_provider()
    try:
        assert provider_pkg.get_provider().name == "mock"
        assert [item.family for item in provider_pkg.get_providers()] == ["mock"]
    finally:
        provider_pkg.reset_provider()


def test_system_provider_exposes_models_list():
    from app.main import app

    with TestClient(app) as client:
        data = client.get("/api/v1/system/provider").json()
    assert data["provider"] == "mock"
    assert data["models"][0]["family"] == "mock"
    assert "family" in data["models"][0]


class _FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code
        self.text = "{}"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "fake error",
                request=httpx.Request("POST", "http://fake"),
                response=self,
            )

    def json(self) -> dict:
        return {"status_code": self.status_code}


class _FakeClient:
    def __init__(self, *, retry_failures: int = 0, status_code: int = 200, **_: object):
        self.calls = 0
        self.retry_failures = retry_failures
        self.status_code = status_code

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def post(self, path: str, json: object = None) -> _FakeResponse:
        self.calls += 1
        if self.calls <= self.retry_failures:
            raise httpx.TimeoutException("simulated timeout")
        return _FakeResponse(self.status_code)


def _make_http_provider(**overrides: object) -> OpenAICompatibleProvider:
    kwargs = {
        "base_url": "http://fake",
        "api_key": "sk-test",
        "vision_model": "vision-model",
        "text_model": "text-model",
        "embedding_model": "embedding-model",
        "name": "test-provider",
        "timeout": 0.1,
        "max_retries": 1,
        "retry_backoff": 0,
    }
    kwargs.update(overrides)
    return OpenAICompatibleProvider(
        **kwargs,
    )


def _transport_mock(handler) -> "httpx.MockTransport":
    return httpx.MockTransport(handler)


def test_http_post_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.TimeoutException("simulated timeout")
        return httpx.Response(200, json={"status_code": 200})

    provider = _make_http_provider(max_retries=3, transport=_transport_mock(handler))
    result = provider._post("/chat/completions", {})
    assert result.data["status_code"] == 200
    assert calls["n"] == 3
    provider.close()


def test_http_post_raises_typed_timeout_after_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    provider = _make_http_provider(max_retries=2, transport=_transport_mock(handler))
    with pytest.raises(ModelTimeoutError):
        provider._post("/chat/completions", {})
    provider.close()


def test_http_post_4xx_raises_without_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "denied"})

    provider = _make_http_provider(max_retries=2, transport=_transport_mock(handler))
    with pytest.raises(ModelUnavailableError):
        provider._post("/chat/completions", {})
    assert calls["n"] == 1  # 4xx（非 429）不重试
    provider.close()


def test_http_post_429_is_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": "rate limited"})

    provider = _make_http_provider(max_retries=2, transport=_transport_mock(handler))
    with pytest.raises(ModelUnavailableError):
        provider._post("/chat/completions", {})
    assert calls["n"] == 3
    provider.close()


# ---------- B5/WP3.1+3.2：台账、解析失败标记、重试计数线程隔离 ----------


def _ledger_rows(provider_name: str) -> list:
    from app.core.db import SessionLocal
    from app.models import LLMCall

    db = SessionLocal()
    try:
        return list(
            db.query(LLMCall)
            .filter(LLMCall.provider == provider_name)
            .order_by(LLMCall.created_at)
            .all()
        )
    finally:
        db.close()


def test_usage_tokens_recorded_in_ledger():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 45},
            },
        )

    from app.services import llm_ledger

    provider = _make_http_provider(
        name="ledger-usage-provider", transport=_transport_mock(handler)
    )
    purpose_token = llm_ledger.current_purpose.set("analyze")
    try:
        result = provider._post("/chat/completions", {"model": "vision-model"})
    finally:
        llm_ledger.current_purpose.reset(purpose_token)
    provider.close()

    rows = _ledger_rows("ledger-usage-provider")
    assert rows, "调用后必须写入台账"
    row = rows[-1]
    assert row.tokens_in == 120 and row.tokens_out == 45
    assert row.purpose == "analyze"
    assert row.status == "success"
    assert row.prompt_version  # prompt 版本必须可归因
    assert result.usage == {"prompt_tokens": 120, "completion_tokens": 45}


def test_parse_failure_flagged_and_marked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "这不是 JSON，模型跑偏了"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    from app.services.guardrail import validate_model_analysis

    provider = _make_http_provider(
        name="ledger-parse-provider", transport=_transport_mock(handler)
    )
    output = provider.analyze([], "楼道堆物")
    provider.close()

    assert output["parse_failed"] is True, "解析失败必须在结果中显式标记"
    guard = validate_model_analysis(output, provider=output.get("provider", ""), model="")
    codes = [v.code for v in guard.violations]
    assert "model_output_unparsed" in codes, "解析失败必须触发人工复核"

    rows = _ledger_rows("ledger-parse-provider")
    assert rows and rows[-1].status == "parse_failed" and rows[-1].parse_failed


def test_retry_count_is_thread_local():
    """并发调用共享 provider 实例时，重试计数不得互相污染。"""
    import threading

    per_thread = threading.local()

    def handler(request: httpx.Request) -> httpx.Response:
        count = getattr(per_thread, "failures_left", 0)
        if count > 0:
            per_thread.failures_left = count - 1
            raise httpx.TimeoutException("simulated timeout")
        return httpx.Response(200, json={"ok": True})

    provider = _make_http_provider(max_retries=3, transport=_transport_mock(handler))
    observed: dict[str, int] = {}
    barrier = threading.Barrier(2)

    def worker(tag: str, failures: int) -> None:
        per_thread.failures_left = failures
        barrier.wait()
        provider._post("/chat/completions", {})
        observed[tag] = provider.last_retry_count

    t1 = threading.Thread(target=worker, args=("zero", 0))
    t2 = threading.Thread(target=worker, args=("two", 2))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    provider.close()
    assert observed == {"zero": 0, "two": 2}
