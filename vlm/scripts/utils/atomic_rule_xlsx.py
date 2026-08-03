"""Shared helpers for exporting atomic_rules.json data to xlsx."""

from __future__ import annotations

import re
from typing import Any


POSITION_RULE_SUFFIX = "_position"
POSITION_LEFT_RIGHT_SWAP = {
    "left": "right",
    "right": "left",
}
_POSITION_TOKEN_SPLIT = re.compile(r"([_\-\s])")

ANNOTATION_VISIBLE_VALUES = ("visible", "invisible")
VISIBLE_STATUS_VALUES = (
    "correct",
    "wrong color",
    "wrong material",
    "wrong shape",
    "wrong_prosition",
    "extra",
)
INVISIBLE_STATUS_VALUES = ("correct invisible", "wrong invisible")
ANNOTATION_STATUS_VALUES = VISIBLE_STATUS_VALUES + INVISIBLE_STATUS_VALUES


def add_annotation_dropdowns(worksheet: Any) -> None:
    """Add the standard visible/status dropdowns to an annotation worksheet."""
    from openpyxl.worksheet.datavalidation import DataValidation

    visible_formula = f'"{",".join(ANNOTATION_VISIBLE_VALUES)}"'
    status_formula = f'"{",".join(ANNOTATION_STATUS_VALUES)}"'
    for validation in list(worksheet.data_validations.dataValidation):
        if validation.type == "list" and validation.formula1 in {visible_formula, status_formula}:
            worksheet.data_validations.dataValidation.remove(validation)

    last_row = max(worksheet.max_row, 2)
    for column in ("E", "G", "I"):
        validation = DataValidation(type="list", formula1=visible_formula, allow_blank=True)
        validation.errorTitle = "无效的可见性"
        validation.error = "请选择 visible 或 invisible。"
        worksheet.add_data_validation(validation)
        validation.add(f"{column}2:{column}{last_row}")
    for column in ("F", "H", "J"):
        validation = DataValidation(type="list", formula1=status_formula, allow_blank=True)
        validation.errorTitle = "无效的视角状态"
        validation.error = "请从下拉列表中选择状态。"
        worksheet.add_data_validation(validation)
        validation.add(f"{column}2:{column}{last_row}")


def normalize_position_value(rule_id: str, value: Any) -> Any:
    """Flip left/right values to the annotator's observation viewpoint.

    Only rule IDs ending in ``_position`` are adjusted. Non-string values are
    returned unchanged.
    """
    if not isinstance(rule_id, str) or not rule_id.lower().endswith(POSITION_RULE_SUFFIX):
        return value
    if not isinstance(value, str):
        return value
    parts = _POSITION_TOKEN_SPLIT.split(value.strip())
    changed = False
    for index, part in enumerate(parts):
        swapped = POSITION_LEFT_RIGHT_SWAP.get(part.lower())
        if swapped:
            parts[index] = swapped
            changed = True
    return "".join(parts) if changed else value
