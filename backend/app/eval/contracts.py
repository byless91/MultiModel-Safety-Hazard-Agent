"""Versioned report identity and honest HTTP/cost accounting."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from app.eval.dataset import EvalCase, EvalDataset
from app.prompts import GUARD_STATEMENT, PROMPT_VERSION, VISION_PROMPT

REPORT_SCHEMA_VERSION = "2.0"
METRICS_SCHEMA_VERSION = "2.0"
ROOT = Path(__file__).resolve().parents[2]


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def sample_identity(cases: list[EvalCase]) -> str:
    rows = []
    for case in cases:
        images = []
        for name in case.image_paths:
            path = Path(name)
            if not path.is_absolute() and case._dataset_dir is not None:
                path = case._dataset_dir / path
            images.append(hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing")
        rows.append({"case": case.model_dump(mode="json", by_alias=True), "images": images})
    return digest(sorted(rows, key=lambda row: row["case"]["id"]))


def knowledge_identity(directory: str | Path) -> str:
    files = sorted((Path(directory) / "chunks").glob("*.jsonl"))
    return digest(
        {
            p.name: [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
            for p in files
        }
    )


def report_identity(dataset: EvalDataset, results: list[dict[str, Any]]) -> dict[str, Any]:
    ids = sorted(row["case"]["case_id"] for row in results)
    configurations = []
    for row in results:
        config = dict(row.get("configuration") or {})
        config.pop("faiss_index_dir", None)  # Cache location does not change the experiment.
        knowledge = config.pop("knowledge_dir", None)
        config["knowledge_digest"] = (
            (row.get("knowledge_digest") or knowledge_identity(knowledge)) if knowledge else None
        )
        if config not in configurations:
            configurations.append(config)
    app = ROOT / "app"
    rule_files = [
        app / "services" / path
        for path in ("human_review.py", "ensemble/judge.py", "ensemble/categories.py", "evidence/judge.py")
    ]
    rule_files.extend(sorted((app / "services/risk_engine").glob("*.py")))
    rules_digest = digest({p.relative_to(app).as_posix(): p.read_text(encoding="utf-8") for p in rule_files})
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT.parent, text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT.parent,
                                            stderr=subprocess.DEVNULL, timeout=5).strip())
    except (OSError, subprocess.SubprocessError):
        revision = "unavailable"
        dirty = None
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "metrics_schema_version": results[0].get("metrics_schema_version", "1.0")
        if results
        else METRICS_SCHEMA_VERSION,
        "dataset_schema_version": dataset.manifest.schema_version,
        "dataset_digest": sample_identity(dataset.cases),
        "sample_ids": ids,
        "sample_digest": sample_identity([c for c in dataset.cases if c.case_id in ids]),
        "configuration_summary": configurations,
        "configuration_digest": digest(sorted(configurations, key=digest)),
        "variant_ids": sorted({row.get("variant", "") for row in results}),
        "prompt_version": PROMPT_VERSION,
        "prompt_digest": digest([VISION_PROMPT, GUARD_STATEMENT]),
        "rule_versions": sorted({row.get("configuration", {}).get("risk_rule_version", "unknown") for row in results}),
        "rules_digest": rules_digest,
        "git_revision": revision,
        "worktree_dirty": dirty,
        "source_digest": digest({p.relative_to(app).as_posix(): p.read_text(encoding="utf-8")
                                  for p in sorted(app.rglob("*.py"))}),
        "model_identifiers": sorted(
            {
                str(item.get("provider", "")) + ":" + str(item.get("model", ""))
                for row in results
                for item in row.get("model_results", [])
            }
            | {
                "served:" + str(event["response_model"])
                for row in results
                for event in row.get("call_statistics", {}).get("events", [])
                if event.get("response_model")
            }
        ),
    }


def load_experiment_file(path: Path | None, *, pricing: bool = False) -> dict[str, Any] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Experiment policy must be an object")
    if pricing:
        if not data.get("currency") or not isinstance(data.get("models"), dict):
            raise ValueError("Pricing requires currency and models")
        for price in data["models"].values():
            for key in ("input_per_million", "output_per_million"):
                value = price.get(key)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError("Pricing must be finite non-negative numbers")
    else:
        from datetime import UTC, datetime

        if datetime.fromisoformat(data["registered_at"]) > datetime.now(UTC):
            raise ValueError("Gate policy must be registered before execution")
        if not data.get("metrics") or data.get("metrics_schema_version") != METRICS_SCHEMA_VERSION:
            raise ValueError("Invalid metric policy")
    return data


def call_statistics(events: list[dict[str, Any]], pricing: dict[str, Any] | None = None) -> dict[str, Any]:
    failed = sum(event["status"] != "success" for event in events)
    cost = 0.0
    unpriced = 0
    pricing = pricing or {}
    currency = pricing.get("currency")
    def usage(event: dict[str, Any], name: str) -> int | None:
        value = event.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    for event in events:
        price = pricing.get("models", {}).get(event.get("response_model") or event["requested_model"])
        tokens_in, tokens_out = usage(event, "tokens_in"), usage(event, "tokens_out")
        if not price or not currency or tokens_in is None or tokens_out is None:
            unpriced += 1
            continue
        cost += (tokens_in * price["input_per_million"] + tokens_out * price["output_per_million"]) / 1_000_000
    return {
        "http_attempt_count": len(events),
        "http_error_count": failed,
        "http_error_rate": round(failed / len(events), 4) if events else None,
        "http_latency_ms_sum": round(sum(e["latency_ms"] for e in events), 3),
        "tokens_in_reported": sum(usage(e, "tokens_in") or 0 for e in events),
        "tokens_out_reported": sum(usage(e, "tokens_out") or 0 for e in events),
        "usage_missing_count": sum(usage(e, "tokens_in") is None or usage(e, "tokens_out") is None for e in events),
        "estimated_cost": round(cost, 8) if not unpriced else None,
        "cost_status": "incomplete" if unpriced else "estimated" if events else "no_http_calls",
        "currency": currency,
        "unpriced_attempt_count": unpriced,
        "pricing_digest": digest(pricing) if pricing else None,
        "response_model_identifiers": sorted({str(e["response_model"]) for e in events if e.get("response_model")}),
        "events": events,
    }
