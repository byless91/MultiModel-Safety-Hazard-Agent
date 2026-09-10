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
from app.services.providers import http as http_module


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


def test_http_post_retries_then_succeeds(monkeypatch):
    fake = _FakeClient(retry_failures=2)
    monkeypatch.setattr(http_module.httpx, "Client", lambda **kw: fake)
    provider = _make_http_provider(max_retries=3)
    result = provider._post("/chat/completions", {})
    assert result["status_code"] == 200
    assert fake.calls == 3


def test_http_post_raises_typed_timeout_after_retries(monkeypatch):
    fake = _FakeClient(retry_failures=10)
    monkeypatch.setattr(http_module.httpx, "Client", lambda **kw: fake)
    provider = _make_http_provider(max_retries=2)
    with pytest.raises(ModelTimeoutError):
        provider._post("/chat/completions", {})
    assert fake.calls == 3


def test_http_post_4xx_raises_without_retry(monkeypatch):
    fake = _FakeClient(status_code=401)
    monkeypatch.setattr(http_module.httpx, "Client", lambda **kw: fake)
    provider = _make_http_provider(max_retries=2)
    with pytest.raises(ModelUnavailableError):
        provider._post("/chat/completions", {})
    assert fake.calls == 1


def test_http_post_429_is_retried(monkeypatch):
    fake = _FakeClient(status_code=429)
    monkeypatch.setattr(http_module.httpx, "Client", lambda **kw: fake)
    provider = _make_http_provider(max_retries=2)
    with pytest.raises(ModelUnavailableError):
        provider._post("/chat/completions", {})
    assert fake.calls == 3
