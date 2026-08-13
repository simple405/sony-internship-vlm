"""Translate SN-7 atomic-rule pairs into natural Chinese and maintain XLSX files."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests

from vlm.scripts._http import direct_http_session
from vlm.scripts._paths import API_ENV_FILE, load_api_env
from vlm.scripts._sn7_artifacts import CATEGORY_OUTPUT_SUFFIXES, find_generated_output
from vlm.scripts._validation import validate_qwen_base_url
from vlm.scripts.utils.atomic_rule_xlsx import (
    TRANSLATION_CACHE_RELATIVE_PATH,
    canonical_rule_value,
    load_translation_cache,
    translation_key,
    write_atomic_rules_xlsx,
)


DEFAULT_DATASET = Path("vlm/data/sn7_data_generation")
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
PROMPT_VERSION = "atomic-rule-natural-cn-v4"
SYSTEM_PROMPT = """你是资深的中文角色设定表编辑。输出会直接进入 XLSX 单元格，任务不是逐词翻译，而是根据 rule_id 的语义，把 value 改写成中国服装、动画角色设定和商品监修表中自然、简洁、独立可读的中文标签。

编辑原则：
1. 先理解 rule_id 表示的属性，再把 value 写成一个完整中文词组。严禁把下划线分隔的英文逐词翻译后用“、”或逗号拼起来。
2. rule_name_cn 要像中文表头：skirt_length -> 裙长，hair_color -> 发色，footwear_type -> 鞋型，legwear_type -> 腿部服饰，top_style -> 上衣款式，bag_color -> 包袋配色。避免“鞋类类型”“腿部穿着类型”这类翻译腔。
3. value_cn 要像中文设定标签，而不是英文语序的直译。优先使用服装行业和日常中文中已经存在的说法。
4. 长度值必须结合对象改写：
   - knee_length -> 及膝长度，不能写“膝、长度”；
   - thigh_length 用“裙摆至大腿中部”或同等自然说法，不能写“及大腿长度”；
   - floor_length 用“裙摆及地”或“拖地长款”，不能写“及地长度”。
5. 服饰值使用约定俗成的名称：knee_high_socks -> 及膝袜；long_sleeve_with_ruffles -> 长袖荷叶边款或“长袖，饰有荷叶边”。
6. none_visible 表示画面中未看到该物件，写“未见鞋子”“鞋子不可见”等自然说法，禁止写“无可见鞋类”。
7. has_* 的布尔值：rule_name_cn 写成自然疑问属性名；true/false 的 value_cn 只写“有”或“无”。has_X_on_Y 必须按中文语序写“Y是否有X”，例如 has_bow_on_waist -> 腰部是否有蝴蝶结，不能写“是否有腰部蝴蝶结”。
8. 组合关系要按中文语序选择连接方式：
   - A_and_B 表示并列配色时写“A和B”“A配B”或其他自然短语；value_cn 中绝对不能出现顿号“、”，也不能写“白色和深绿色双色”这类混合句式；
   - A_with_B_trim 写“A配B滚边/镶边”；
   - A_with_B_tip 写“A色，尾尖/末端为B色”；
   - gradient 写“由A渐变至B”或“A到B渐变”。
9. 保留必要的数字、专名和无法翻译的标识，但不得添加原文没有的材质、形状、位置或风格信息。
10. value_cn 中严禁出现顿号“、”。多个颜色、部件或特征必须改写成带“和”“配”“带”“渐变至”等关系词的完整中文短语。
11. 每项输出前，在心里连读“rule_name_cn：value_cn”。如果不像中国编辑会写进表格的人话，就先重写；不要输出分析过程。

输出严格 JSON，根对象只能包含 translations。每项必须原样返回 index，并包含 rule_name_cn、value_cn。不要输出 Markdown，也不要增加解释字段。"""


def translation_quality_issues(
    pair: RulePair,
    rule_name_cn: str,
    value_cn: str,
) -> list[str]:
    """Return concrete signs that a translation is still machine-like."""
    issues: list[str] = []
    combined = f"{rule_name_cn} {value_cn}"
    if re.search(r"[A-Za-z]+_[A-Za-z]", combined):
        issues.append("contains an untranslated identifier")
    if "、" in value_cn:
        issues.append("value_cn contains forbidden dunhao punctuation")
    for phrase in ("无可见", "及大腿长度", "及地长度"):
        if phrase in value_cn:
            issues.append(f"contains machine-like phrase: {phrase}")
    if re.search(r"和[^，。；]+双色", value_cn):
        issues.append("mixed two alternative Chinese color constructions")
    if re.search(r"(?:膝|大腿|脚踝|地面)[、,，]\s*长度", value_cn):
        issues.append("length value was translated token by token")
    if pair.rule_id.startswith("has_") and pair.value in {"true", "false"}:
        expected = "有" if pair.value == "true" else "无"
        if value_cn != expected:
            issues.append(f"boolean value must be {expected}")
    if pair.rule_id == "has_bow_on_waist" and rule_name_cn != "腰部是否有蝴蝶结":
        issues.append("has_bow_on_waist must use natural Chinese word order")
    if pair.value == "none_visible" and not re.search(r"未见|不可见|未显示", value_cn):
        issues.append("none_visible must describe an item as unseen")
    if pair.value == "knee_length" and pair.rule_id.endswith("_length"):
        if value_cn != "及膝长度":
            issues.append("knee_length must be 及膝长度")
    if pair.value == "knee_high_socks" and value_cn != "及膝袜":
        issues.append("knee_high_socks must be 及膝袜")
    return issues


@dataclass(frozen=True)
class RulePair:
    """One unique rule/value pair collected from the dataset."""

    key: str
    rule_id: str
    value: str
    locations: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    """Parse translation and workbook synchronization arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--assignment-csv", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--env-file", type=Path, default=API_ENV_FILE)
    parser.add_argument("--model", default="", help="Default: QWEN_TEXT_MODEL or qwen-plus.")
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--overwrite-translations", action="store_true")
    parser.add_argument("--overwrite-xlsx", action="store_true")
    parser.add_argument(
        "--skip-xlsx",
        action="store_true",
        help="Populate the translation cache without creating or rewriting workbooks.",
    )
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--poll-interval", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON through a sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def collect_rule_pairs(atomic_root: Path) -> dict[str, RulePair]:
    """Collect all unique contextual rule/value pairs from canonical JSON files."""
    collected: dict[str, dict[str, Any]] = {}
    files = sorted(atomic_root.glob("*/atomic_rules.json"))
    if not files:
        raise FileNotFoundError(f"No atomic_rules.json files found under {atomic_root}")
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        rules = payload.get("atomic_rules", [])
        if not isinstance(rules, list):
            raise ValueError(f"atomic_rules must be a list: {path}")
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id", "")).strip()
            if not rule_id:
                raise ValueError(f"Empty rule id in {path}")
            value = canonical_rule_value(rule.get("value"))
            key = translation_key(rule_id, rule.get("value"))
            entry = collected.setdefault(
                key,
                {"rule_id": rule_id, "value": value, "locations": set()},
            )
            entry["locations"].add(str(rule.get("location", "")))
    return {
        key: RulePair(
            key=key,
            rule_id=str(entry["rule_id"]),
            value=str(entry["value"]),
            locations=tuple(sorted(entry["locations"])),
        )
        for key, entry in collected.items()
    }


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from plain or fenced model output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise TypeError("Qwen translation response root must be an object")
    return parsed


def parse_translation_response(text: str, batch: list[RulePair]) -> list[dict[str, str]]:
    """Validate a model response and return translations in input order."""
    payload = extract_json_object(text)
    rows = payload.get("translations")
    if not isinstance(rows, list):
        raise ValueError("Qwen response translations must be a list")
    by_index: dict[int, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Qwen translation entry must be an object")
        index = row.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(batch):
            raise ValueError(f"Invalid Qwen translation index: {index!r}")
        if index in by_index:
            raise ValueError(f"Duplicate Qwen translation index: {index}")
        rule_name = str(row.get("rule_name_cn", "")).strip()
        value_cn = str(row.get("value_cn", "")).strip()
        if not rule_name or not value_cn or "未翻译" in rule_name + value_cn:
            raise ValueError(f"Incomplete Qwen translation at index {index}")
        if not re.search(r"[\u3400-\u9fff]", rule_name):
            raise ValueError(f"rule_name_cn is not Chinese at index {index}: {rule_name!r}")
        issues = translation_quality_issues(batch[index], rule_name, value_cn)
        if issues:
            raise ValueError(
                f"Machine-like Qwen translation at index {index} "
                f"({batch[index].rule_id}={batch[index].value}): {'; '.join(issues)}"
            )
        by_index[index] = {"rule_name_cn": rule_name, "value_cn": value_cn}
    if set(by_index) != set(range(len(batch))):
        missing = sorted(set(range(len(batch))) - set(by_index))
        raise ValueError(f"Qwen response omitted translation indexes: {missing}")
    return [by_index[index] for index in range(len(batch))]


def response_text(payload: dict[str, Any]) -> str:
    """Extract text content from an OpenAI-compatible chat completion response."""
    message = payload["choices"][0]["message"]
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        )
    if str(content).strip():
        return str(content)
    for key in ("reasoning_content", "reasoning"):
        if str(message.get(key, "")).strip():
            return str(message[key])
    raise ValueError("Qwen response has no message content")


def translate_batch(
    batch: list[RulePair],
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int,
    max_retries: int,
    max_tokens: int,
    response_observer: Callable[[str], None] | None = None,
) -> list[dict[str, str]]:
    """Translate one bounded batch with retry handling."""
    items = [
        {
            "index": index,
            "rule_id": pair.rule_id,
            "value": pair.value,
            "location": list(pair.locations),
        }
        for index, pair in enumerate(batch)
    ]
    request_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps({"items": items}, ensure_ascii=False),
            },
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
    with direct_http_session() as session:
        for attempt in range(max_retries + 1):
            try:
                response = session.post(
                    base_url.rstrip("/") + "/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                    timeout=timeout,
                    allow_redirects=False,
                )
                if response.status_code in {400, 401, 403}:
                    response.raise_for_status()
                response.raise_for_status()
                raw_text = response_text(response.json())
                if response_observer is not None:
                    response_observer(raw_text)
                return parse_translation_response(raw_text, batch)
            except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
                status_code = getattr(getattr(exc, "response", None), "status_code", 0)
                retryable = status_code in {0, 429} or status_code >= 500
                if not retryable or attempt >= max_retries:
                    break
                time.sleep(min(30.0, 2.0**attempt))
    raise RuntimeError(f"Qwen translation batch failed after retries: {last_error}")


def cache_payload(
    translations: dict[str, dict[str, str]],
    *,
    dataset_dir: Path,
    model: str,
    source_pair_count: int,
    status: str,
) -> dict[str, Any]:
    """Build the persistent translation-cache document."""
    return {
        "schema_version": "atomic_rule_translation_cache.v1",
        "status": status,
        "dataset_dir": str(dataset_dir),
        "model": model,
        "source_pair_count": source_pair_count,
        "translated_pair_count": len(translations),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "translations": {key: translations[key] for key in sorted(translations)},
    }


def translate_all(
    pairs: dict[str, RulePair],
    translations: dict[str, dict[str, str]],
    *,
    dataset_dir: Path,
    cache_path: Path,
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int,
    workers: int,
    timeout: int,
    max_retries: int,
    max_tokens: int,
) -> dict[str, dict[str, str]]:
    """Translate every missing pair and checkpoint after each completed batch."""
    translations = {
        key: entry for key, entry in translations.items() if key in pairs
    }
    pending = [pairs[key] for key in sorted(pairs) if key not in translations]
    batches = [pending[index : index + batch_size] for index in range(0, len(pending), batch_size)]
    if not batches:
        write_json_atomic(
            cache_path,
            cache_payload(
                translations,
                dataset_dir=dataset_dir,
                model=model,
                source_pair_count=len(pairs),
                status="complete",
            ),
        )
        return translations

    errors: list[str] = []
    completed_pairs = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_batch = {
            executor.submit(
                translate_batch,
                batch,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=timeout,
                max_retries=max_retries,
                max_tokens=max_tokens,
            ): batch
            for batch in batches
        }
        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                translated_rows = future.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
                print(
                    json.dumps(
                        {"status": "translation_batch_error", "size": len(batch), "error": str(exc)},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            for pair, translated in zip(batch, translated_rows, strict=True):
                translations[pair.key] = {
                    "rule_id": pair.rule_id,
                    "value": pair.value,
                    "rule_name_cn": translated["rule_name_cn"],
                    "value_cn": translated["value_cn"],
                    "model": model,
                    "updated_at": now,
                }
            completed_pairs += len(batch)
            write_json_atomic(
                cache_path,
                cache_payload(
                    translations,
                    dataset_dir=dataset_dir,
                    model=model,
                    source_pair_count=len(pairs),
                    status="in_progress",
                ),
            )
            print(
                json.dumps(
                    {
                        "status": "translation_batch_ok",
                        "batch_size": len(batch),
                        "completed_this_run": completed_pairs,
                        "cached": len(translations),
                        "total": len(pairs),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    if errors:
        raise RuntimeError(f"{len(errors)} translation batches failed; rerun to resume")
    write_json_atomic(
        cache_path,
        cache_payload(
            translations,
            dataset_dir=dataset_dir,
            model=model,
            source_pair_count=len(pairs),
            status="complete",
        ),
    )
    return translations


def read_assignments(path: Path) -> dict[str, str]:
    """Read sample-to-category assignments."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        str(row.get("sample_id", "")).strip(): str(row.get("primary_category", "")).strip()
        for row in rows
        if str(row.get("sample_id", "")).strip()
    }


def find_rules_file(sample_dir: Path, sample_id: str) -> Path | None:
    """Find canonical or copied atomic rules in one sample directory."""
    for name in ("atomic_rules.json", f"{sample_id}_atomic_rules.json"):
        candidate = sample_dir / name
        if candidate.is_file():
            return candidate
    return None


def workbook_is_stale(
    workbook: Path,
    rules_path: Path,
    cache_mtime: float,
    *,
    overwrite: bool,
) -> bool:
    """Return whether a workbook needs creation or regeneration."""
    if overwrite or not workbook.is_file():
        return True
    return workbook.stat().st_mtime < max(rules_path.stat().st_mtime, cache_mtime)


def sync_workbooks(
    dataset_dir: Path,
    assignments: dict[str, str],
    translations: dict[str, dict[str, str]],
    cache_path: Path,
    *,
    overwrite: bool,
) -> dict[str, int]:
    """Create atomic XLSX files and refresh stale generated/deliverable XLSX files."""
    counts = {"atomic_written": 0, "generated_rewritten": 0, "deliverable_rewritten": 0}
    cache_mtime = cache_path.stat().st_mtime
    atomic_root = dataset_dir / "atomic_rules"
    for rules_path in sorted(atomic_root.glob("*/atomic_rules.json")):
        sample_id = rules_path.parent.name
        category = assignments.get(sample_id, "")
        if category not in CATEGORY_OUTPUT_SUFFIXES:
            raise ValueError(f"Missing valid category assignment for {sample_id}: {category!r}")
        workbook = rules_path.parent / f"{sample_id}.xlsx"
        if workbook_is_stale(workbook, rules_path, cache_mtime, overwrite=overwrite):
            write_atomic_rules_xlsx(
                rules_path,
                workbook,
                category,
                translation_cache=translations,
            )
            counts["atomic_written"] += 1

    generated_root = dataset_dir / "generated"
    for category, output_suffix in CATEGORY_OUTPUT_SUFFIXES.items():
        category_dir = generated_root / category
        if not category_dir.is_dir():
            continue
        for sample_dir in sorted(path for path in category_dir.iterdir() if path.is_dir()):
            sample_id = sample_dir.name
            workbook = sample_dir / f"{sample_id}.xlsx"
            if find_generated_output(sample_dir, sample_id, output_suffix) is None:
                continue
            rules_path = find_rules_file(sample_dir, sample_id)
            if rules_path is None:
                continue
            if workbook_is_stale(workbook, rules_path, cache_mtime, overwrite=overwrite):
                write_atomic_rules_xlsx(
                    rules_path,
                    workbook,
                    category,
                    translation_cache=translations,
                )
                counts["generated_rewritten"] += 1

    deliverable_root = dataset_dir / "deliverables"
    for category in CATEGORY_OUTPUT_SUFFIXES:
        category_dir = deliverable_root / category
        if not category_dir.is_dir():
            continue
        for sample_dir in sorted(path for path in category_dir.iterdir() if path.is_dir()):
            sample_id = sample_dir.name
            rules_path = sample_dir / "atomic_rules.json"
            workbook = sample_dir / f"{sample_id}.xlsx"
            if not rules_path.is_file():
                continue
            if workbook_is_stale(workbook, rules_path, cache_mtime, overwrite=overwrite):
                write_atomic_rules_xlsx(
                    rules_path,
                    workbook,
                    category,
                    translation_cache=translations,
                )
                counts["deliverable_rewritten"] += 1
    return counts


def main() -> None:
    """Translate all rule pairs, then maintain natural-Chinese XLSX workbooks."""
    args = parse_args()
    if min(args.batch_size, args.workers, args.timeout, args.max_tokens, args.poll_interval) < 1:
        raise ValueError("batch size, workers, timeout, max tokens, and poll interval must be positive")
    if args.max_retries < 0:
        raise ValueError("--max-retries must be non-negative")
    dataset_dir = args.dataset_dir.resolve()
    assignment_csv = (
        args.assignment_csv
        or dataset_dir
        / "reports"
        / "merchandise_category_assignment"
        / "merchandise_category_assignments.csv"
    ).resolve()
    cache_path = (args.cache or dataset_dir / TRANSLATION_CACHE_RELATIVE_PATH).resolve()
    pairs = collect_rule_pairs(dataset_dir / "atomic_rules")
    assignments = read_assignments(assignment_csv)
    load_api_env(args.env_file)
    model = args.model.strip() or os.environ.get("QWEN_TEXT_MODEL", "").strip() or DEFAULT_MODEL
    base_url = validate_qwen_base_url(os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL))
    translations = {} if args.overwrite_translations else load_translation_cache(cache_path)
    pending_count = sum(key not in translations for key in pairs)
    print(
        json.dumps(
            {
                "status": "translation_started",
                "pairs": len(pairs),
                "cached": len(translations),
                "pending": pending_count,
                "model": model,
                "cache": str(cache_path),
                "dry_run": args.dry_run,
                "skip_xlsx": bool(getattr(args, "skip_xlsx", False)),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.dry_run:
        return
    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if pending_count and not api_key:
        raise SystemExit("QWEN_API_KEY is required for pending translations")
    translations = translate_all(
        pairs,
        translations,
        dataset_dir=dataset_dir,
        cache_path=cache_path,
        api_key=api_key,
        base_url=base_url,
        model=model,
        batch_size=args.batch_size,
        workers=args.workers,
        timeout=args.timeout,
        max_retries=args.max_retries,
        max_tokens=args.max_tokens,
    )
    if getattr(args, "skip_xlsx", False):
        print(
            json.dumps(
                {"status": "xlsx_skipped", "cached": len(translations)},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return
    first_sync = True
    while True:
        counts = sync_workbooks(
            dataset_dir,
            assignments,
            translations,
            cache_path,
            overwrite=args.overwrite_xlsx and first_sync,
        )
        first_sync = False
        print(
            json.dumps(
                {"status": "xlsx_sync", "cached": len(translations), **counts},
                ensure_ascii=False,
            ),
            flush=True,
        )
        if not args.follow:
            break
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
