import json
from pathlib import Path

from openpyxl import Workbook

from vlm.scripts.audit_atomic_rule_chinese_values import audit_cache, audit_workbook


def test_audit_cache_finds_dunhao_in_value_cn(tmp_path: Path):
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps(
            {
                "translations": {
                    "key": {
                        "rule_id": "bag_color",
                        "value": "white_and_green",
                        "value_cn": "白色、绿色",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    findings = audit_cache(cache)

    assert len(findings) == 1
    assert findings[0]["value_cn"] == "白色、绿色"


def test_audit_workbook_scans_only_chinese_value_column(tmp_path: Path):
    path = tmp_path / "sample.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("规则名称", "取值"))
    sheet.append(("头发、颜色", "白色、绿色"))
    workbook.save(path)
    workbook.close()

    findings = audit_workbook(path)

    assert len(findings) == 1
    assert findings[0]["cell"] == "B2"
