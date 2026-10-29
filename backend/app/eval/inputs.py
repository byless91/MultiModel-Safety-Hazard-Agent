"""Decode declared images before any model call; never substitute text input."""

from __future__ import annotations

import hashlib
import warnings
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.config import Settings
from app.eval.dataset import EvalCase
from app.services.providers.base import ImageInput

FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}


def load_case_images(case: EvalCase, settings: Settings) -> tuple[list[ImageInput], dict[str, Any]]:
    images: list[ImageInput] = []
    report: dict[str, Any] = {"declared": len(case.image_paths), "loaded": 0, "errors": [], "files": []}
    if len(case.image_paths) > settings.max_images:
        report["errors"].append({"code": "too_many_images"})
        return [], report
    for index, name in enumerate(case.image_paths):
        try:
            path = Path(name)
            if not path.is_absolute():
                if case._dataset_dir is None:
                    raise ValueError("dataset_directory_required")
                path = case._dataset_dir / path
            path = path.resolve()
            if not path.is_file():
                raise ValueError("image_missing")
            if path.stat().st_size > settings.max_file_bytes:
                raise ValueError("image_too_large")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    kind = image.format
                    if kind not in FORMATS:
                        raise ValueError("image_format_unsupported")
                    image.verify()
                with Image.open(path) as image:
                    image.load()  # Decode pixels too: a plausible header is insufficient.
            images.append(ImageInput(filename=path.name, path=path, mime_type=FORMATS[kind]))
            report["files"].append({"index": index, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        except ValueError as exc:
            code = str(exc) if str(exc) in {
                "dataset_directory_required", "image_missing", "image_too_large", "image_format_unsupported",
            } else "image_corrupt"
            report["errors"].append({"index": index, "code": code})
        except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            report["errors"].append({"index": index, "code": "image_corrupt"})
    report["loaded"] = len(images)
    return ([] if report["errors"] else images), report
