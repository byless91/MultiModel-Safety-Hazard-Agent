"""业务 Prometheus 指标定义（B1/WP3.3）。

HTTP 层通用指标（延迟/状态码/QPS）由 prometheus_fastapi_instrumentator
在 main.py 暴露的 /metrics 端点提供；本模块只定义业务指标并在调用点埋点。
B3 任务队列落地后补充队列深度（queue depth）指标。
"""

from prometheus_client import Counter, Histogram

WORKFLOW_DURATION = Histogram(
    "safety_hazard_workflow_duration_seconds",
    "单次研判工作流端到端耗时（秒）",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

WORKFLOW_TOTAL = Counter(
    "safety_hazard_workflow_total",
    "研判工作流执行次数（按最终状态）",
    labelnames=("status",),
)

MODEL_REQUESTS = Counter(
    "safety_hazard_model_requests_total",
    "模型调用次数（按 provider 与结果状态）",
    labelnames=("provider", "status"),
)

MODEL_RETRIES = Counter(
    "safety_hazard_model_retries_total",
    "模型调用重试次数（按 provider）",
    labelnames=("provider",),
)


def record_model_run(provider: str, status: str, retry_count: int = 0) -> None:
    """记录一次模型调用的结果与重试次数（analyzer 调用点使用）。"""
    MODEL_REQUESTS.labels(provider=provider, status=status).inc()
    if retry_count:
        MODEL_RETRIES.labels(provider=provider).inc(retry_count)
