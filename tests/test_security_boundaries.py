"""Security and failure-signaling regression tests for retained workflows."""

from __future__ import annotations

from argparse import Namespace
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vlm.scripts import extract_atomic_rules as atomic_extraction
from vlm.scripts._validation import (
    resolve_manifest_path,
    validate_path_component,
    validate_qwen_base_url,
)
from vlm.scripts.generate import generate_paired_front_view as paired_generation
from vlm.scripts.generate import generate_sn7_multiview as sn7_generation
from vlm.scripts.generate.prompt_renderer import render_generation_prompt
from vlm.scripts.generate.runninghub_client import (
    download_result,
    safe_result_extension,
    submit_task,
)
from vlm.scripts.supervise import run_paired_front_view_review as paired_review


PROMPT_TEMPLATE = (
    "{{MERCHANDISE_CATEGORY}}\n{{VIEW_REQUIREMENTS}}\n{{CATEGORY_REQUIREMENTS}}"
)


def test_path_component_and_manifest_path_reject_traversal(tmp_path: Path):
    with pytest.raises(ValueError):
        validate_path_component("../outside", "sample ID")
    with pytest.raises(ValueError):
        resolve_manifest_path(tmp_path, "../outside.png", "image_file")


def test_atomic_extraction_rejects_manifest_id_before_writing_error(
    monkeypatch, tmp_path: Path
):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    manifest = dataset / "manifest.csv"
    manifest.write_text(
        "post_id,image_path\n../escape,image/input.png\n", encoding="utf-8"
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("prompt", encoding="utf-8")
    args = Namespace(
        manifest=manifest,
        output_root=dataset / "atomic_rules",
        prompt=prompt,
        env_file=tmp_path / "missing.env",
        model="qwen3-vl-plus",
        limit=0,
        workers=1,
        temperature=0.0,
        max_tokens=100,
        timeout=1,
        max_retries=0,
        dry_run=True,
        overwrite=False,
        new_only=False,
    )
    monkeypatch.setattr(atomic_extraction, "parse_args", lambda: args)
    monkeypatch.setenv("QWEN_BASE_URL", atomic_extraction.DEFAULT_BASE_URL)

    with pytest.raises(ValueError, match="sample ID"):
        atomic_extraction.main()

    assert not (dataset / "escape" / "error.json").exists()


def test_qwen_url_accepts_only_official_https_host():
    assert (
        validate_qwen_base_url("https://dashscope.aliyuncs.com/compatible-mode/v1/")
        == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    for value in (
        "http://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://localhost/v1",
        "https://dashscope.aliyuncs.com.evil.example/v1",
    ):
        with pytest.raises(ValueError):
            validate_qwen_base_url(value)


def test_shared_prompt_renders_front_and_multiview_contexts():
    front = render_generation_prompt(PROMPT_TEMPLATE, "dataset_figurine", "front")
    multiview = render_generation_prompt(PROMPT_TEMPLATE, "backpack", "multiview")
    assert "正面" in front and "PVC" in front
    assert "三个正交视角" in multiview and "双肩背包" in multiview
    assert "{{" not in front + multiview


def test_runninghub_extension_and_endpoint_are_allowlisted(monkeypatch):
    assert safe_result_extension("PNG") == ".png"
    assert safe_result_extension("../../cmd.exe") == ".png"
    post = MagicMock()
    monkeypatch.setattr("vlm.scripts.generate.runninghub_client.requests.post", post)
    with pytest.raises(ValueError):
        submit_task(
            "secret",
            "prompt",
            ["https://example.com/input.png"],
            endpoint="https://evil.example/v1",
        )
    post.assert_not_called()


def test_download_rejects_private_urls_without_request(monkeypatch, tmp_path: Path):
    get = MagicMock()
    monkeypatch.setattr("vlm.scripts.generate.runninghub_client.requests.get", get)
    with pytest.raises(ValueError):
        download_result({"url": "https://127.0.0.1/image.png"}, tmp_path / "out.png")
    get.assert_not_called()


def test_download_rejects_hostname_resolving_to_private_address(
    monkeypatch, tmp_path: Path
):
    get = MagicMock()
    monkeypatch.setattr("vlm.scripts.generate.runninghub_client.requests.get", get)
    monkeypatch.setattr(
        "vlm.scripts.generate.runninghub_client.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("10.0.0.8", 443)),
        ],
    )
    with pytest.raises(ValueError, match="Private or local"):
        download_result(
            {"url": "https://internal.example/image.png"}, tmp_path / "out.png"
        )
    get.assert_not_called()


def test_download_size_limit_removes_partial_file(monkeypatch, tmp_path: Path):
    response = MagicMock()
    response.headers = {"Content-Type": "image/png"}
    response.iter_content.return_value = [b"1234", b"5"]
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    monkeypatch.setattr("vlm.scripts.generate.runninghub_client.MAX_DOWNLOAD_BYTES", 4)
    monkeypatch.setattr(
        "vlm.scripts.generate.runninghub_client.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ],
    )
    session = MagicMock()
    session.get.return_value = response
    monkeypatch.setattr(
        "vlm.scripts.generate.runninghub_client.direct_http_session",
        lambda: nullcontext(session),
    )
    output = tmp_path / "out.png"
    with pytest.raises(RuntimeError, match="exceeds"):
        download_result({"url": "https://cdn.example.com/image.png"}, output)
    assert not output.exists()
    assert not output.with_suffix(".png.part").exists()


def test_download_rejects_non_raster_image_content_type(
    monkeypatch, tmp_path: Path
):
    response = MagicMock()
    response.headers = {"Content-Type": "image/svg+xml"}
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    monkeypatch.setattr(
        "vlm.scripts.generate.runninghub_client.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ],
    )
    session = MagicMock()
    session.get.return_value = response
    monkeypatch.setattr(
        "vlm.scripts.generate.runninghub_client.direct_http_session",
        lambda: nullcontext(session),
    )
    output = tmp_path / "out.png"

    with pytest.raises(RuntimeError, match="content type"):
        download_result({"url": "https://cdn.example.com/image.svg"}, output)

    assert not output.exists()
    assert not output.with_suffix(".png.part").exists()


def test_paired_generation_exits_nonzero_when_a_sample_fails(
    monkeypatch, tmp_path: Path
):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(PROMPT_TEMPLATE, encoding="utf-8")
    image = tmp_path / "input.png"
    gold = tmp_path / "input.json"
    image.write_bytes(b"image")
    gold.write_text("{}", encoding="utf-8")
    sample = paired_generation.Sample("sample", image, ".png", 5, gold)
    args = Namespace(
        input_root=tmp_path,
        output_root=tmp_path / "out",
        prompt_file=prompt_file,
        sample_id=[],
        limit=1,
        dry_run=True,
        workers=1,
        poll_interval=1,
        timeout=1,
    )
    monkeypatch.setattr(paired_generation, "parse_args", lambda: args)
    monkeypatch.setattr(paired_generation, "read_manifest", lambda root: [sample])
    monkeypatch.setattr(
        paired_generation,
        "process_one",
        lambda *unused, **kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )
    with pytest.raises(SystemExit) as exc:
        paired_generation.main()
    assert exc.value.code == 1


def test_sn7_generation_exits_nonzero_when_a_sample_fails(monkeypatch, tmp_path: Path):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(PROMPT_TEMPLATE, encoding="utf-8")
    args = Namespace(
        sample_id=["sample"],
        source_dir=tmp_path,
        atomic_dir=tmp_path,
        direct_output_dir=tmp_path / "out",
        prompt_file=prompt_file,
        aspect_ratio="21:9",
        resolution="1k",
        output_suffix="figurine",
        category="dataset_figurine",
        poll_interval=1,
        timeout=1,
        workers=1,
        stop_on_error=False,
        keep_debug_files=False,
        dry_run=True,
    )
    monkeypatch.setattr(sn7_generation, "parse_args", lambda: args)
    monkeypatch.setattr(
        sn7_generation,
        "run_one",
        lambda *unused: (_ for _ in ()).throw(RuntimeError("failed")),
    )
    with pytest.raises(SystemExit) as exc:
        sn7_generation.main()
    assert exc.value.code == 1


def test_review_rejects_unofficial_endpoint_before_request(monkeypatch, tmp_path: Path):
    post = MagicMock()
    monkeypatch.setattr(paired_review.requests, "post", post)
    with pytest.raises(ValueError):
        paired_review.call_qwen_review(
            api_key="secret",
            base_url="https://evil.example/v1",
            model="qwen",
            image_path=tmp_path / "image.png",
            prompt_text="review",
            timeout=1,
        )
    post.assert_not_called()
