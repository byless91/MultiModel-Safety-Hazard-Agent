from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "多模态基层安全隐患智能研判与处置辅助系统"
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

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_images: int = 3
    max_followups: int = 2
    conf_weights: str = "0.3,0.3,0.2,0.2"

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
        for field in ("upload_dir", "knowledge_dir", "faiss_index_dir"):
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
