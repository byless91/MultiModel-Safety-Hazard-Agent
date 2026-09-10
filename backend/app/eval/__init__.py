"""Evaluation dataset schemas, validation and versioned loading.

The evaluation system is intentionally kept separate from the runtime API so
that it can grow to 100/200 cases without touching assessment persistence.
"""

from app.eval.dataset import (
    EvalCase,
    EvalDataset,
    EvalDatasetManifest,
    EvalSourceType,
    load_dataset,
    validate_case_row,
)
from app.eval.metrics import (
    METRIC_ORDER,
    build_error_analysis,
    compute_metrics,
    error_by_dimension,
    error_summary,
    failure_cases,
    metric_definitions,
)

__all__ = [
    "EvalCase",
    "EvalDataset",
    "EvalDatasetManifest",
    "EvalSourceType",
    "METRIC_ORDER",
    "build_error_analysis",
    "compute_metrics",
    "error_by_dimension",
    "error_summary",
    "failure_cases",
    "load_dataset",
    "metric_definitions",
    "validate_case_row",
]
