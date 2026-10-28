from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "多模态基层安全隐患智能研判与处置辅助系统"
    app_version: str = "0.1.0"
    debug: bool = True
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'app.db').as_posix()}"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    knowledge_dir: Path = BACKEND_DIR / "data" / "knowledge"
    faiss_index_dir: Path = BACKEND_DIR / "data" / "faiss"

    provider_mode: str = "auto"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vision_model: str = "qwen-vl-plus"
    text_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v3"
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_vision_model: str = "glm-4v-flash"
    zhipu_text_model: str = "glm-4-flash"
    zhipu_embedding_model: str = "embedding-2"
    model_timeout: float = 60.0
    model_max_retries: int = 1
    model_retry_backoff: float = 0.5
    risk_rule_version: str = "risk-engine-v1"
    refine_with_evidence: bool = True
    reranker_enabled: bool = True
    reranker_top_k: int = 5
    enable_risk_engine: bool = True
    enable_evidence_rag: bool = True

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_bearer_token: str = ""
    max_images: int = 3
    max_followups: int = 2
    max_file_bytes: int = 10 * 1024 * 1024
    max_document_bytes: int = 20 * 1024 * 1024
    conf_weights: str = "0.3,0.3,0.2,0.2"

    # B3：异步任务化。sync = 现状（同步等待结果）；async = 202 + 任务表 + 轮询
    workflow_mode: Literal["sync", "async"] = "sync"
    # B4：认证模式。none = 本地开发不鉴权；token = 静态 Bearer（兼容旧部署）；
    # jwt = 用户体系（/api/v1/auth/token + 角色权限）。生产必须 jwt 或 token。
    auth_mode: Literal["none", "token", "jwt"] = "none"
    auth_jwt_secret: str = "dev-insecure-secret-change-me"
    auth_token_expire_minutes: int = 720
    upload_url_ttl_minutes: int = 60
    rate_limit_enabled: bool = False
    # B5：LLM 并发与预算
    max_concurrent_llm_calls: int = 4
    daily_token_budget: int = 0  # 0 = 不限；>0 时当日 tokens 超限后拒绝新研判
    # B5：演示模式置信度加成（默认关；生产与评测路径不得开启）
    mock_demo_boost: bool = False
    # B5：检索参数收敛
    retrieval_top_k: int = 5
    embedding_recovery_seconds: float = 60.0
    rerank_vector_weight: float = 0.4
    rerank_lexical_weight: float = 0.4
    rerank_metadata_weight: float = 0.2
    rate_limit_assessments_per_minute: int = 5
    rate_limit_login_per_minute: int = 10
    langgraph_checkpoint_path: Path = BACKEND_DIR / "data" / "langgraph.db"
    job_stale_minutes: int = 10
    job_lease_seconds: float = Field(default=30.0, ge=3)
    job_monitor_seconds: float = Field(default=5.0, gt=0, le=10)
    job_stop_grace_seconds: float = Field(default=5.0, ge=0, le=30)
    idempotency_ttl_hours: int = 24
    compare_dedup_minutes: int = 5

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def confidence_weights(self) -> list[float]:
        try:
            return [float(x) for x in self.conf_weights.split(",") if x.strip()]
        except ValueError:
            return [0.3, 0.3, 0.2, 0.2]

    @property
    def active_provider(self) -> str:
        if self.provider_mode == "mock":
            return "mock"
        if self.provider_mode == "openai":
            return "openai"
        return "openai" if (self.dashscope_api_key or self.zhipu_api_key) else "mock"

    @model_validator(mode="after")
    def resolve_relative_paths(self) -> "Settings":
        for field in ("upload_dir", "knowledge_dir", "faiss_index_dir", "langgraph_checkpoint_path"):
            value = getattr(self, field)
            if isinstance(value, Path) and not value.is_absolute():
                setattr(self, field, BACKEND_DIR / value)
        if self.database_url.startswith("sqlite:///./") or self.database_url.startswith(
            "sqlite:///../"
        ):
            relative = self.database_url.replace("sqlite:///", "", 1)
            self.database_url = f"sqlite:///{(BACKEND_DIR / relative).resolve().as_posix()}"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
