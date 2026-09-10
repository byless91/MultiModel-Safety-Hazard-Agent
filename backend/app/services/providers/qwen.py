"""Qwen-VL model family on DashScope's OpenAI-compatible API."""

from app.services.providers.http import OpenAICompatibleProvider


class QwenProvider(OpenAICompatibleProvider):
    name = "dashscope"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        vision_model: str = "qwen-vl-plus",
        text_model: str = "qwen-plus",
        embedding_model: str = "text-embedding-v3",
        timeout: float = 60.0,
        max_retries: int = 1,
        retry_backoff: float = 0.5,
    ) -> None:
        super().__init__(
            name="dashscope",
            family="qwen-vl",
            base_url=base_url,
            api_key=api_key,
            vision_model=vision_model,
            text_model=text_model,
            embedding_model=embedding_model,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
        )
