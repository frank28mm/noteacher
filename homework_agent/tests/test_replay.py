from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPLAY_ROOT = Path(__file__).resolve().parent / "replay_data"
SAMPLES_DIR = REPLAY_ROOT / "samples"
IMAGES_DIR = REPLAY_ROOT / "images"


@dataclass(frozen=True)
class ReplaySample:
    path: Path
    payload: Dict[str, Any]


def _load_samples() -> List[ReplaySample]:
    if not SAMPLES_DIR.exists():
        return []
    samples: List[ReplaySample] = []
    for p in sorted(SAMPLES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            raise AssertionError(f"Invalid JSON: {p} ({e})")
        if not isinstance(data, dict):
            raise AssertionError(f"Sample must be a JSON object: {p}")
        samples.append(ReplaySample(path=p, payload=data))
    return samples


def _get_local_image_paths(sample: ReplaySample) -> List[Path]:
    inp = sample.payload.get("input") or {}
    if not isinstance(inp, dict):
        return []
    local = inp.get("local_images") or []
    if isinstance(local, str):
        local = [local]
    if not isinstance(local, list):
        return []
    out: List[Path] = []
    for rel in local:
        s = str(rel or "").strip()
        if not s:
            continue
        p = IMAGES_DIR / s
        out.append(p)
    return out


def _assert_sample_schema(sample: ReplaySample) -> None:
    data = sample.payload
    sid = data.get("sample_id")
    assert isinstance(sid, str) and sid.strip(), f"missing sample_id in {sample.path}"
    subject = str(data.get("subject") or "").strip().lower()
    assert subject in {
        "math",
        "english",
    }, f"invalid subject in {sample.path}: {subject}"

    inp = data.get("input")
    assert isinstance(inp, dict), f"missing input in {sample.path}"

    # We support local-images-first for CI safety.
    local_images = inp.get("local_images")
    image_urls = inp.get("image_urls")
    base64_img = inp.get("or_base64")
    assert (
        local_images or image_urls or base64_img
    ), f"input must include one of local_images/image_urls/or_base64: {sample.path}"

    exp = data.get("expected_output")
    assert exp is None or isinstance(
        exp, dict
    ), f"expected_output must be object if provided: {sample.path}"


def _assert_images_exist(sample: ReplaySample) -> None:
    paths = _get_local_image_paths(sample)
    for p in paths:
        assert (
            p.exists()
        ), f"missing local replay image: {p} (referenced by {sample.path})"


@pytest.mark.parametrize(
    "sample",
    _load_samples(),
    ids=lambda s: getattr(getattr(s, "path", None), "name", "sample"),
)
def test_replay_sample_schema(sample: ReplaySample) -> None:
    _assert_sample_schema(sample)
    _assert_images_exist(sample)


def test_replay_dataset_present_or_skipped() -> None:
    """
    Ensure the replay dataset is wired correctly.
    This test does NOT force having samples; it provides a clear skip for early-stage repos.
    """
    samples = _load_samples()
    if not samples:
        pytest.skip(
            "No replay samples found in homework_agent/tests/replay_data/samples/"
        )


@pytest.mark.skipif(
    os.environ.get("RUN_REPLAY_LIVE") != "1",
    reason="set RUN_REPLAY_LIVE=1 to run live replay",
)
def test_replay_live_placeholder() -> None:
    """
    Placeholder for future live replay runs (calls real providers / requires secrets).
    Keeping this explicit avoids accidental network/provider calls in CI.
    """
    pytest.skip(
        "Live replay runner not implemented yet (requires provider stubs or secrets)."
    )
