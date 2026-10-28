"""One text policy for API inputs and persisted job inputs before model calls."""

from app.services.guardrail.input_guard import MAX_DESCRIPTION_LENGTH, inspect_text


def require_model_text(text: str, *, max_length: int | None = MAX_DESCRIPTION_LENGTH) -> None:
    if not isinstance(text, str):
        raise ValueError("模型输入必须是文本")
    errors = [item for item in inspect_text(text, max_length=max_length) if item.severity == "error"]
    if errors:
        raise ValueError("；".join(f"{item.code}: {item.message}" for item in errors))
