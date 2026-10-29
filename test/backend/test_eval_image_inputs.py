"""R6/T15: images reach providers and invalid inputs never become text runs."""

import json

import pytest
from app.core.config import get_settings
from app.eval.dataset import load_dataset
from app.eval.evaluation import build_evaluation_report, pick_variant, run_evaluation_case
from app.services.providers.mock import MockProvider
from app.services.rag import RAGService
from PIL import Image


def dataset_at(tmp_path, image_paths):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({
        "id": "image-case", "description": "商场安全出口被货物堵住", "scenario": "消防",
        "expected_category": "占用疏散通道", "expected_level": 1,
        "image_paths": image_paths, "user_text": "已确认出口被堵住",
    }, ensure_ascii=False), encoding="utf-8")
    return load_dataset(path, fail_on_issues=True)


def test_provider_receives_decodable_image_content(tmp_path, monkeypatch):
    Image.new("RGB", (16, 12), "red").save(tmp_path / "photo.png")
    dataset = dataset_at(tmp_path, ["photo.png"])
    received = []

    class RecordingProvider(MockProvider):
        def analyze(self, images, text, **kwargs):
            received.append([(image.mime_type, image.path.read_bytes()) for image in images])
            return super().analyze(images, text, **kwargs)

    settings = get_settings().model_copy(update={"refine_with_evidence": False})
    provider = RecordingProvider()
    monkeypatch.chdir(tmp_path.parent)
    trace = run_evaluation_case(dataset.cases[0], pick_variant("full"), settings=settings,
                                providers=[provider], rag=RAGService(settings, provider))
    assert received and received[0] == [("image/png", (tmp_path / "photo.png").read_bytes())]
    assert trace["image_input"]["loaded"] == 1
    assert len(trace["image_input"]["files"][0]["sha256"]) == 64


def test_followup_reuses_exact_same_images(tmp_path, monkeypatch):
    Image.new("RGB", (8, 8)).save(tmp_path / "photo.webp")
    dataset = dataset_at(tmp_path, ["photo.webp"])
    calls = []

    def workflow(**kwargs):
        calls.append(kwargs)
        return {"status": "needs_more_info" if len(calls) == 1 else "awaiting_human_review"}

    monkeypatch.setattr("app.services.workflow.run_workflow", workflow)
    run_evaluation_case(dataset.cases[0], pick_variant("full"), settings=get_settings(),
                        providers=[MockProvider()], rag=object())
    assert len(calls) == 2
    assert calls[0]["images"] is calls[1]["images"]
    assert calls[1]["images"][0].mime_type == "image/webp"
    assert calls[1]["followup_answer"] == dataset.cases[0].user_text


@pytest.mark.parametrize("kind", ["missing", "corrupt", "truncated", "unsupported", "oversized", "too_many"])
def test_invalid_images_fail_before_provider_or_workflow(tmp_path, monkeypatch, kind):
    path = tmp_path / "photo.png"
    if kind != "missing":
        Image.new("RGB", (16, 16)).save(path)
    if kind == "corrupt":
        path.write_bytes(b"not an image")
    if kind == "truncated":
        path.write_bytes(path.read_bytes()[:35])
    if kind == "unsupported":
        Image.new("RGB", (8, 8)).save(path, format="BMP")
    dataset = dataset_at(tmp_path, ["photo.png"] * (4 if kind == "too_many" else 1))
    settings = get_settings().model_copy(update={"max_file_bytes": 1} if kind == "oversized" else {})

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid image must not execute workflow or construct providers")

    monkeypatch.setattr("app.eval.evaluation.build_providers", forbidden)
    monkeypatch.setattr("app.services.workflow.run_workflow", forbidden)
    trace = run_evaluation_case(dataset.cases[0], pick_variant("full"), settings=settings)
    assert trace["status"] == "input_failed"
    assert trace["image_input"]["errors"]
    summary, markdown = build_evaluation_report(dataset, [trace], provider_mode="mock")
    assert summary["dataset_overview"]["declared_image_count"] >= 1
    assert summary["dataset_overview"]["loaded_image_count"] == 0
    assert summary["dataset_overview"]["input_failed_count"] == 1
    assert "输入失败案例：1" in markdown


def test_text_case_is_explicitly_not_image_validation(tmp_path):
    dataset = dataset_at(tmp_path, [])
    trace = run_evaluation_case(dataset.cases[0], pick_variant("full"))
    assert trace["image_input"] == {"declared": 0, "loaded": 0, "errors": [], "files": []}
