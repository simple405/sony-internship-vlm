"""Convert annotation .xlsx workbooks to CSV without assuming final workflow.

The converter reads the first worksheet in each workbook using only the Python
standard library. It preserves the source header as-is and also emits a manifest
with a lightweight schema guess. If annotator workbook layouts change, this
script still gives us inspectable CSVs before writing a layout-specific adapter.
"""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any


XML_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

DEFAULT_OUTPUT_DIR = Path("vlm/tmp/annotation_xlsx_converted")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert annotation xlsx files to CSV.")
    parser.add_argument("--input", type=Path, required=True, help="An .xlsx file or a directory containing .xlsx files.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--recursive", action="store_true", help="Recursively find .xlsx files when --input is a directory.")
    parser.add_argument("--include-empty", action="store_true", help="Write CSV files even when the worksheet has no data rows.")
    return parser.parse_args()


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter.upper()) - 64
    return index - 1


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("a:v", XML_NS)
    inline_node = cell.find("a:is", XML_NS)
    if cell_type == "s" and value_node is not None and value_node.text is not None:
        return shared_strings[int(value_node.text)]
    if cell_type == "inlineStr" and inline_node is not None:
        return "".join(text.text or "" for text in inline_node.findall(".//a:t", XML_NS))
    if value_node is not None and value_node.text is not None:
        return value_node.text
    return ""


def read_xlsx_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", XML_NS):
                shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", XML_NS)))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relationships.findall("rel:Relationship", XML_NS)}
        sheet = workbook.find(".//a:sheet", XML_NS)
        if sheet is None:
            return []
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not rel_id:
            return []
        target = rel_map[rel_id].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target

        worksheet = ET.fromstring(archive.read(target))
        rows: list[list[str]] = []
        for row in worksheet.findall(".//a:sheetData/a:row", XML_NS):
            values: list[str] = []
            for cell in row.findall("a:c", XML_NS):
                index = column_index(cell.attrib.get("r", "A1"))
                while len(values) < index:
                    values.append("")
                values.append(cell_value(cell, shared_strings).strip())
            rows.append(values)
        return rows


def find_xlsx_files(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() == ".xlsx" else []
    pattern = "**/*.xlsx" if recursive else "*.xlsx"
    return sorted(item for item in path.glob(pattern) if item.is_file() and not item.name.startswith("~$"))


def detect_schema(header: list[str]) -> str:
    columns = {item.strip() for item in header}
    if {"finding_id", "view"} <= columns and ({"feature_key"} <= columns or {"element_name"} <= columns):
        return "human_visual_findings"
    if {"rule_id", "rule_validity", "atomic_value"} <= columns:
        return "atomic_rule_audit"
    if {"human_finding_id", "atomic_rule_id", "candidate_match_type"} <= columns:
        return "human_to_atomic_rule_mapping"
    if {"front_visible", "front_status", "side_visible", "side_status", "back_visible", "back_status"} <= columns:
        return "v3_rule_level"
    return "unknown"


def rows_to_dicts(rows: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    if not rows:
        return [], []
    header = [cell.strip() for cell in rows[0]]
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        record = {column: (row[index].strip() if index < len(row) else "") for index, column in enumerate(header)}
        if any(record.values()):
            records.append(record)
    return header, records


def safe_output_name(path: Path) -> str:
    return path.with_suffix(".csv").name


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    files = find_xlsx_files(args.input, args.recursive)
    manifest: list[dict[str, Any]] = []
    for xlsx_path in files:
        rows = read_xlsx_rows(xlsx_path)
        header, records = rows_to_dicts(rows)
        schema = detect_schema(header)
        output_path = args.output_dir / safe_output_name(xlsx_path)
        wrote_csv = bool(records or args.include_empty)
        if wrote_csv:
            write_csv(output_path, records, header)
        manifest.append(
            {
                "source_xlsx": str(xlsx_path),
                "output_csv": str(output_path) if wrote_csv else "",
                "schema_guess": schema,
                "columns": len(header),
                "data_rows": len(records),
                "wrote_csv": wrote_csv,
            }
        )

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(args.input),
        "output_dir": str(args.output_dir),
        "xlsx_files": len(files),
        "csv_files_written": sum(1 for row in manifest if row["wrote_csv"]),
    }
    write_csv(
        args.output_dir / "conversion_manifest.csv",
        manifest,
        ["source_xlsx", "output_csv", "schema_guess", "columns", "data_rows", "wrote_csv"],
    )
    write_json(args.output_dir / "summary.json", {**summary, "manifest": manifest})
    print(json.dumps({"status": "finished", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
