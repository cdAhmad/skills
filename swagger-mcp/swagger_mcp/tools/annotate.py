"""swagger_annotate MCP tool — 基于 Swagger JSON 为 Kotlin Bean 补充 KDoc 注释。

导入自原 swagger_annotate/scripts/ 的核心模块。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 将原 swagger_annotate scripts 目录加入 path，以便导入其子模块
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "swagger_annotate", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from swagger_annotate.parser import (
    load_swagger_json,
    build_swagger_map,
    get_flat_field_map,
    match_class_to_definition,
    get_class_path_info,
)
from swagger_annotate.kt_annotator import (
    parse_kotlin_file,
    generate_class_kdoc,
)

from ..common.loader import download_to_tempfile


# 手动映射（使用者按需添加）
MANUAL_COMMENTS: dict[str, dict] = {}


def run(
    swagger_url: str,
    beans_dir: str,
    dry_run: bool = False,
    check_only: bool = False,
) -> dict:
    """执行注释补充，返回结构化结果。

    Returns:
        {
            "ok": bool,
            "files_modified": int,
            "total_changes": int,
            "changes": [{"file": str, "field": str, "comment": str, "type": str}],
            "errors": [str],
        }
    """
    result: dict = {
        "ok": True,
        "files_modified": 0,
        "total_changes": 0,
        "changes": [],
        "errors": [],
    }

    # 1. 加载 Swagger JSON
    tmp_file = None
    try:
        from ..common.loader import _is_url
        if _is_url(swagger_url):
            tmp_file = download_to_tempfile(swagger_url)
            swagger_path = tmp_file
        else:
            swagger_path = swagger_url
            if not os.path.isfile(swagger_path):
                result["ok"] = False
                result["errors"].append(f"文件不存在: {swagger_path}")
                return result

        raw = load_swagger_json(swagger_path)
        swagger_map = build_swagger_map(raw)
        flat_map = get_flat_field_map(swagger_map)
    except Exception as e:
        result["ok"] = False
        result["errors"].append(f"加载 Swagger 失败: {e}")
        return result
    finally:
        if tmp_file and os.path.isfile(tmp_file):
            try:
                os.unlink(tmp_file)
            except Exception:
                pass

    # 2. 遍历 Kotlin 文件
    beans_path = Path(beans_dir)
    if not beans_path.is_dir():
        result["ok"] = False
        result["errors"].append(f"目录不存在: {beans_dir}")
        return result

    kt_files = sorted(beans_path.rglob("*.kt"))

    for kt_file in kt_files:
        try:
            file_changes = _process_one_file(
                kt_file, flat_map, swagger_map, dry_run
            )
            if file_changes:
                result["files_modified"] += 1
                result["total_changes"] += len(file_changes)
                result["changes"].extend(file_changes)
        except Exception as e:
            result["errors"].append(f"{kt_file}: {e}")

    if check_only and result["total_changes"] > 0:
        result["ok"] = False

    return result


def _process_one_file(
    filepath: Path,
    flat_map: dict,
    swagger_map: dict,
    dry_run: bool,
) -> list[dict]:
    """处理单个 Kotlin 文件，返回变更列表。"""
    changes: list[dict] = []

    info = parse_kotlin_file(filepath)
    if not info.fields:
        return changes

    manual_class = MANUAL_COMMENTS.get(info.class_name, {})
    manual_fields = manual_class.get("fields", {})

    field_names = [f.name for f in info.fields]
    matched_def = match_class_to_definition(field_names, swagger_map)
    swagger_props = matched_def.get("properties", {}) if matched_def else {}
    path_info = get_class_path_info(matched_def)

    for field in info.fields:
        orig_name = ""
        target_desc = manual_fields.get(field.name, "")
        if not target_desc:
            sw_val = swagger_props.get(field.name) or flat_map.get(field.name)
            if sw_val:
                orig_name, target_desc = sw_val[0], sw_val[1]
        if not target_desc:
            continue

        comment_text = target_desc
        if orig_name and orig_name != field.name:
            comment_text = f"{orig_name}: {target_desc}"

        existing_desc = field.get_description()
        if field.has_kdoc() and existing_desc:
            if orig_name and orig_name != field.name and orig_name not in existing_desc:
                pass  # 需更新
            else:
                continue  # 注释已完整

        changes.append({
            "file": str(filepath),
            "field": field.name,
            "comment": comment_text,
            "type": "field_kdoc",
        })

    # 类级别 KDoc
    if info.needs_class_kdoc():
        manual_kdoc = manual_class.get("class_kdoc", "")
        if manual_kdoc:
            new_kdoc = manual_kdoc
        elif path_info:
            new_kdoc = generate_class_kdoc(path_info)
        else:
            new_kdoc = ""

        if new_kdoc:
            changes.append({
                "file": str(filepath),
                "field": "[class KDoc]",
                "comment": new_kdoc.replace("\n", " "),
                "type": "class_kdoc",
            })

    # 非 dry_run 时实际写入文件
    if changes and not dry_run:
        _apply_changes(filepath, info, flat_map, swagger_map, manual_class, path_info)

    return changes


def _apply_changes(
    filepath: Path,
    info,
    flat_map: dict,
    swagger_map: dict,
    manual_class: dict,
    path_info: dict | None,
) -> None:
    """实际写入文件（与 annotate_beans.py 的 process_file 逻辑一致）。"""
    import re

    manual_fields = manual_class.get("fields", {})
    field_names = [f.name for f in info.fields]
    matched_def = match_class_to_definition(field_names, swagger_map)
    swagger_props = matched_def.get("properties", {}) if matched_def else {}

    ops: list[dict] = []

    for field in info.fields:
        orig_name = ""
        target_desc = manual_fields.get(field.name, "")
        if not target_desc:
            sw_val = swagger_props.get(field.name) or flat_map.get(field.name)
            if sw_val:
                orig_name, target_desc = sw_val[0], sw_val[1]
        if not target_desc:
            continue

        comment_text = target_desc
        if orig_name and orig_name != field.name:
            comment_text = f"{orig_name}: {target_desc}"

        existing_desc = field.get_description()
        if field.has_kdoc() and existing_desc:
            if orig_name and orig_name != field.name and orig_name not in existing_desc:
                pass
            else:
                continue

        # 删除旧注释行
        for j in range(field.line_idx - 1, -1, -1):
            s = info.all_lines[j].strip()
            if s.startswith('/**') or s.startswith('*/') or s.startswith('*') or s.startswith('/*') or s.startswith('//'):
                ops.append({"line": j, "action": "delete"})
            elif s == '' and ops and ops[-1]["action"] == "delete":
                ops.append({"line": j, "action": "delete"})
            else:
                break

        ops.append({
            "line": field.line_idx,
            "action": "strip_inline_comment",
        })

        indent = ""
        m = re.match(r'^(\s*)', info.all_lines[field.line_idx])
        if m:
            indent = m.group(1)
        comment_line = f"{indent}/** {comment_text} */"

        ops.append({
            "line": field.line_idx,
            "action": "insert_before",
            "content": comment_line,
        })

    # 类级别 KDoc
    if info.needs_class_kdoc():
        manual_kdoc = manual_class.get("class_kdoc", "")
        if manual_kdoc:
            new_kdoc = manual_kdoc
        elif path_info:
            new_kdoc = generate_class_kdoc(path_info)
        else:
            new_kdoc = ""

        if new_kdoc:
            class_idx = info.class_start_idx
            for cl in reversed(new_kdoc.split('\n')):
                ops.append({
                    "line": class_idx,
                    "action": "insert_before",
                    "content": cl,
                })

    if not ops:
        return

    # 按行号从大到小排序
    ops.sort(key=lambda o: o["line"], reverse=True)
    # 反转同行 insert_before
    i = 0
    while i < len(ops):
        if ops[i]["action"] == "insert_before":
            j = i + 1
            while j < len(ops) and ops[j]["line"] == ops[i]["line"] and ops[j]["action"] == "insert_before":
                j += 1
            if j > i + 1:
                ops[i:j] = reversed(ops[i:j])
            i = j
        else:
            i += 1

    new_lines = list(info.all_lines)
    for op in ops:
        idx = op["line"]
        if op["action"] == "delete":
            if idx < len(new_lines):
                del new_lines[idx]
        elif op["action"] == "insert_before":
            new_lines.insert(idx, op["content"])
        elif op["action"] == "strip_inline_comment":
            current = new_lines[idx]
            current = re.sub(r'\s*//\s*fl\s*$', '', current)
            current = re.sub(r'\s*//\s*[^\n]*$', '', current)
            new_lines[idx] = current

    content = '\n'.join(new_lines)
    if not content.endswith('\n'):
        content += '\n'
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
