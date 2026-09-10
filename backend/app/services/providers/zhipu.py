"""GLM-V model family on Zhipu BigModel's OpenAI-compatible API."""

from app.services.providers.http import OpenAICompatibleProvider


class ZhipuProvider(OpenAICompatibleProvider):
    name = "zhipu"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        vision_model: str = "glm-4v-flash",
        text_model: str = "glm-4-flash",
        embedding_model: str = "embedding-2",
        timeout: float = 60.0,
        max_retries: int = 1,
        retry_backoff: float = 0.5,
    ) -> None:
        super().__init__(
            name="zhipu",
            family="glm-v",
            base_url=base_url,
            api_key=api_key,
            vision_model=vision_model,
            text_model=text_model,
            embedding_model=embedding_model,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
        )
