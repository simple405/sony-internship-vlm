"""Shared helpers for exporting atomic_rules.json data to xlsx."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HEAD_ONLY_CATEGORIES = ("head_key_chain", "cake_roll", "backpack")
XLSX_COLUMNS = (
    "sample_id",
    "rule_id",
    "location",
    "value",
    "front_visible",
    "front_status",
    "side_visible",
    "side_status",
    "back_visible",
    "back_status",
    "note",
)


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
    """Return the atomic-rule value exactly as emitted.

    Historical trial scripts flipped ``left`` and ``right`` while writing xlsx
    files. The current SN-7 contract requires atomic_rules values to already be
    in annotator/viewer coordinates, so export must not rewrite them.
    """
    return value


def write_atomic_rules_xlsx(
    json_path: Path,
    output_path: Path,
    category: str,
    location_map: dict[str, str] | None = None,
) -> int:
    """Export atomic rules to the standard three-view annotation workbook."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    rules = data.get("atomic_rules", [])
    if not isinstance(rules, list):
        raise ValueError(f"atomic_rules must be a list: {json_path}")
    locations = location_map or {}
    if category in HEAD_ONLY_CATEGORIES:
        rules = [
            rule
            for rule in rules
            if isinstance(rule, dict)
            and (
                rule.get("location") == "head"
                or (
                    rule.get("location") not in {"head", "body"}
                    and locations.get(str(rule.get("id")), "body") == "head"
                )
            )
        ]

    sample_id = str(data.get("code") or data.get("sample_id") or json_path.parent.name)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for column, name in enumerate(XLSX_COLUMNS, start=1):
        cell = sheet.cell(row=1, column=column, value=name)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9D9D9")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_number, rule in enumerate(rules, start=2):
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id", ""))
        location = str(rule.get("location") or locations.get(rule_id, ""))
        if location not in {"head", "body"}:
            raise ValueError(f"Rule {rule_id!r} is missing location=head/body")
        value = normalize_position_value(rule_id, rule.get("value", ""))
        row = [sample_id, rule_id, location, value]
        row.extend([""] * (len(XLSX_COLUMNS) - len(row)))
        for column, cell_value in enumerate(row, start=1):
            sheet.cell(row=row_number, column=column, value=cell_value)

    add_annotation_dropdowns(sheet)
    for column_cells in sheet.columns:
        width = max((len(str(cell.value or "")) for cell in column_cells), default=0)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(width + 4, 40)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    workbook.save(temp_path)
    workbook.close()
    temp_path.replace(output_path)
    return len(rules)
