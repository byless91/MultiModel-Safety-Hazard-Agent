"""Run every configured vision provider in parallel over the same input."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.services.ensemble.schemas import ModelRunResult, MultiModelResult
from app.services.providers.base import (
    BaseProvider,
    ImageInput,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.services.providers.mock import MockProvider


def _run_one(
    provider: BaseProvider,
    images: list[ImageInput],
    text: str,
    *,
    rag_evidence: list[str] | None = None,
    ocr_texts: list[str] | None = None,
) -> ModelRunResult:
    started = time.perf_counter()
    try:
        analysis = provider.analyze(
            images,
            text,
            rag_evidence=rag_evidence,
            ocr_texts=ocr_texts,
        )
        status = "success"
        error_type = ""
        error_message = ""
    except ModelTimeoutError as exc:
        analysis = None
        status = "failed"
        error_type = "timeout"
        error_message = str(exc)[:120]
    except ModelUnavailableError as exc:
        analysis = None
        status = "failed"
        error_type = "unavailable"
        error_message = str(exc)[:120]
    except Exception as exc:
        analysis = None
        status = "failed"
        error_type = "unexpected"
        error_message = str(exc)[:120]
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return ModelRunResult(
        provider=provider.name,
        family=provider.family,
        model=getattr(provider, "vision_model", ""),
        model_version=getattr(provider, "model_version", ""),
        status=status,
        error_type=error_type,
        error_message=error_message,
        latency_ms=latency_ms,
        retry_count=getattr(provider, "last_retry_count", 0),
        analysis=analysis,
    )


def _mock_fallback_run(
    images: list[ImageInput],
    text: str,
    *,
    ocr_texts: list[str] | None = None,
) -> ModelRunResult:
    started = time.perf_counter()
    analysis = MockProvider().analyze(images, text, ocr_texts=ocr_texts)
    analysis["vision_confidence"] = min(
        float(analysis.get("vision_confidence", 0.5)),
        0.5,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return ModelRunResult(
        provider="mock",
        family="mock",
        model="mock-vision",
        status="mock_fallback",
        latency_ms=latency_ms,
        retry_count=0,
        analysis=analysis,
    )


def run_parallel_analysis(
    providers: list[BaseProvider],
    images: list[ImageInput],
    text: str,
    *,
    rag_evidence: list[str] | None = None,
    ocr_texts: list[str] | None = None,
) -> MultiModelResult:
    """Return one result per configured provider plus ensemble bookkeeping.

    Real providers run in a small thread pool; this project's provider calls
    are synchronous HTTP calls, so threads give real parallelism without
    forcing the whole LangGraph flow to become async.
    """
    real = [provider for provider in providers if provider.name != "mock"]
    if not real:
        run = _run_one(
            providers[0] if providers else MockProvider(),
            images,
            text,
            rag_evidence=rag_evidence,
            ocr_texts=ocr_texts,
        )
        return MultiModelResult(
            ensemble_mode="mock",
            results=[run],
            primary=run,
            succeeded=1 if run.status == "success" else 0,
            failed=0,
            total_latency_ms=run.latency_ms,
        )

    if len(real) == 1:
        runs = [
            _run_one(
                real[0],
                images,
                text,
                rag_evidence=rag_evidence,
                ocr_texts=ocr_texts,
            )
        ]
    else:
        with ThreadPoolExecutor(max_workers=len(real)) as pool:
            futures = [
                pool.submit(
                    _run_one,
                    provider,
                    images,
                    text,
                    rag_evidence=rag_evidence,
                    ocr_texts=ocr_texts,
                )
                for provider in real
            ]
            runs = [future.result() for future in futures]

    succeeded = [run for run in runs if run.status == "success"]
    if succeeded:
        primary = succeeded[0]
        if len(real) == 1:
            mode = "single_real"
        else:
            mode = "full" if len(succeeded) == len(runs) else "partial"
    else:
        fallback = _mock_fallback_run(images, text, ocr_texts=ocr_texts)
        runs = [*runs, fallback]
        primary = fallback
        mode = "fallback"

    return MultiModelResult(
        ensemble_mode=mode,
        results=runs,
        primary=primary,
        succeeded=sum(1 for run in runs if run.status == "success"),
        failed=sum(1 for run in runs if run.status == "failed"),
        total_latency_ms=round(sum(run.latency_ms for run in runs), 1),
    )
