"""Tests for runninghub_client.py — load_api_env, require_api_key, _auth_headers (mocked)."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from vlm.scripts.generate.runninghub_client import (
    load_api_env,
    require_api_key,
    _auth_headers,
)


# ---------------------------------------------------------------------------
# load_api_env
# ---------------------------------------------------------------------------

def test_load_api_env_basic(tmp_path, monkeypatch):
    env_file = tmp_path / "api.env"
    env_file.write_text("MY_KEY=secret123\n", encoding="utf-8")
    monkeypatch.delenv("MY_KEY", raising=False)
    load_api_env(env_file)
    assert os.environ.get("MY_KEY") == "secret123"

def test_load_api_env_strips_quotes(tmp_path, monkeypatch):
    env_file = tmp_path / "api.env"
    env_file.write_text("QUOTED_KEY='hello'\n", encoding="utf-8")
    monkeypatch.delenv("QUOTED_KEY", raising=False)
    load_api_env(env_file)
    assert os.environ.get("QUOTED_KEY") == "hello"

def test_load_api_env_strips_double_quotes(tmp_path, monkeypatch):
    env_file = tmp_path / "api.env"
    env_file.write_text('DQ_KEY="world"\n', encoding="utf-8")
    monkeypatch.delenv("DQ_KEY", raising=False)
    load_api_env(env_file)
    assert os.environ.get("DQ_KEY") == "world"

def test_load_api_env_skips_comments(tmp_path, monkeypatch):
    env_file = tmp_path / "api.env"
    env_file.write_text("# this is a comment\nVALID_KEY=value\n", encoding="utf-8")
    monkeypatch.delenv("VALID_KEY", raising=False)
    load_api_env(env_file)
    assert os.environ.get("VALID_KEY") == "value"

def test_load_api_env_skips_blank_lines(tmp_path, monkeypatch):
    env_file = tmp_path / "api.env"
    env_file.write_text("\n\nBLANK_AFTER=yes\n\n", encoding="utf-8")
    monkeypatch.delenv("BLANK_AFTER", raising=False)
    load_api_env(env_file)
    assert os.environ.get("BLANK_AFTER") == "yes"

def test_load_api_env_does_not_overwrite_existing(tmp_path, monkeypatch):
    env_file = tmp_path / "api.env"
    env_file.write_text("EXISTING_KEY=new_value\n", encoding="utf-8")
    monkeypatch.setenv("EXISTING_KEY", "original_value")
    load_api_env(env_file)
    assert os.environ.get("EXISTING_KEY") == "original_value"

def test_load_api_env_nonexistent_file(tmp_path):
    # Should not raise even when file is missing
    load_api_env(tmp_path / "nonexistent.env")

def test_load_api_env_bom_file(tmp_path, monkeypatch):
    env_file = tmp_path / "api.env"
    env_file.write_bytes(b"\xef\xbb\xbfBOM_KEY=bomvalue\n")
    monkeypatch.delenv("BOM_KEY", raising=False)
    load_api_env(env_file)
    assert os.environ.get("BOM_KEY") == "bomvalue"


# ---------------------------------------------------------------------------
# require_api_key
# ---------------------------------------------------------------------------

def test_require_api_key_returns_key(monkeypatch):
    monkeypatch.setenv("RUNNINGHUB_API_KEY", "test_key_123")
    key = require_api_key()
    assert key == "test_key_123"

def test_require_api_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("RUNNINGHUB_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="RUNNINGHUB_API_KEY"):
        require_api_key()

def test_require_api_key_raises_when_whitespace_only(monkeypatch):
    monkeypatch.setenv("RUNNINGHUB_API_KEY", "   ")
    with pytest.raises(RuntimeError):
        require_api_key()


# ---------------------------------------------------------------------------
# _auth_headers
# ---------------------------------------------------------------------------

def test_auth_headers_with_json_content():
    headers = _auth_headers("mykey", json_content=True)
    assert headers["Authorization"] == "Bearer mykey"
    assert headers["Content-Type"] == "application/json"

def test_auth_headers_without_json_content():
    headers = _auth_headers("mykey", json_content=False)
    assert headers["Authorization"] == "Bearer mykey"
    assert "Content-Type" not in headers

def test_auth_headers_default_is_json():
    headers = _auth_headers("k")
    assert "Content-Type" in headers
