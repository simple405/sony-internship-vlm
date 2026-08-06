"""Regression tests for dataset evaluator CLI defaults."""

import sys

from vlm.scripts.dataset.evaluate_element_extraction_predictions import parse_args


def test_evaluator_enables_embeddings_by_default(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["evaluate_element_extraction_predictions"])
    assert parse_args().use_embeddings is True


def test_evaluator_can_disable_embeddings_explicitly(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["evaluate_element_extraction_predictions", "--no-embeddings"])
    assert parse_args().use_embeddings is False
