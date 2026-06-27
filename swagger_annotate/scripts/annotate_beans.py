#!/usr/bin/env python3
"""
根据 Swagger JSON 为 Kotlin Bean 类补充完整注释。

用法:
    python annotate_beans.py --input https://example.com/v2/api-docs
    python annotate_beans.py --input swagger.json
    python annotate_beans.py --dry-run
    python annotate_beans.py --check-only
"""

import sys
import os
import re
import argparse
import tempfile
from pathlib import Path
from urllib.parse import urlparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

from swagger_annotate.parser import (
    load_swagger_json,
    build_swagger_map,
    build_flat_field_map,
    get_flat_field_map,
    get_property_desc,
    match_class_to_definition,
    get_class_path_info,
)
from swagger_annotate.kt_annotator import (
    parse_kotlin_file,
    ClassInfo,
    FieldInfo,
    generate_class_kdoc,
)


def _is_url(s: str) -> bool:
    """判断字符串是否为 URL。"""
    return bool(urlparse(s).scheme in ("http", "https"))


def _normalize_swagger_url(url: str) -> str:
    """
    将 Swagger UI 地址自动转换为 api-docs 端点。

    doc.html / swagger-ui.html → 提取域名 + /v2/api-docs
    已是 api-docs 路径 → 原样返回
    """
    parsed = urlparse(url)
    path = parsed.path.lower()

    # 已是 api-docs 结尾，直接返回
    if path.endswith("/v2/api-docs") or path.endswith("/v3/api-docs"):
        return url

    # doc.html 或 swagger-ui 等 Swagger UI 地址 → 拼接 /v2/api-docs
    if any(kw in path for kw in ("doc.html", "swagger-ui")):
        return f"{parsed.scheme}://{parsed.netloc}/v2/api-docs"

    # URL 以 / 结尾或只有域名 → 拼接 v2/api-docs
    if path in ("", "/"):
        return f"{parsed.scheme}://{parsed.netloc}/v2/api-docs"

    return url


# Swagger definitions 之外需要手动补充注释的类（使用者按需添加）
MANUAL_COMMENTS: dict[str, dict] = {
    # 格式示例:
    # "ClassName": {
    #     "class_kdoc": "/**\n * 类描述\n */",
    #     "fields": {"fieldName": "字段描述"},
    # },
}


def get_swagger_path(source: str) -> tuple[Path | None, bool]:
    """
    获取 Swagger JSON 文件路径。

    返回 (path, is_temp):
    - 本地文件 → (path, False)，无需清理
    - URL → 下载到临时文件 → (path, True)，用后需删除
    """
    if not _is_url(source):
        path = Path(source)
        if path.is_file():
            return path, False
        print(f"ERROR: file not found: {source}")
        return None, False

    # URL 规范化：doc.html → /v2/api-docs
    source = _normalize_swagger_url(source)
    import urllib.request
    try:
        print(f"[fetch] {source} ...")
        req = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
        # 写入临时文件
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="swagger_v2_")
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(data)
        print(f"[ok] {tmp_path} ({len(data):,} bytes)")
        return Path(tmp_path), True
    except Exception as e:
        print(f"[warn] fetch failed: {e}")
        return None, False


def process_file(
    filepath: Path,
    flat_map: dict[str, str],
    swagger_map: dict,
    manual_map: dict,
    dry_run: bool = False,
) -> list[str]:
    """处理单个 Kotlin 文件，返回变更描述列表。"""
    changes = []
    info = parse_kotlin_file(filepath)
    if not info.fields:
        return changes

    class_name = info.class_name
    manual_class = manual_map.get(class_name, {})
    manual_fields = manual_class.get("fields", {})

    # 尝试通过字段集匹配 Swagger definition
    field_names = [f.name for f in info.fields]
    matched_def = match_class_to_definition(field_names, swagger_map)
    swagger_props = matched_def.get("properties", {}) if matched_def else {}
    path_info = get_class_path_info(matched_def)



    # 收集所有修改操作：(line_idx, action, data)
    # action: "delete" | "insert" | "replace_line" | "insert_class_kdoc"
    ops: list[dict] = []

    for field in info.fields:
        # 获取描述：优先手动映射，其次 Swagger
        orig_name = ""
        target_desc = manual_fields.get(field.name, "")
        if not target_desc:
            sw_val = swagger_props.get(field.name) or flat_map.get(field.name)
            if sw_val:
                orig_name, target_desc = sw_val[0], sw_val[1]
        if not target_desc:
            continue

        # 生成注释文本：原始字段名与混淆名不同时，附加前缀
        comment_text = target_desc
        if orig_name and orig_name != field.name:
            comment_text = f"{orig_name}: {target_desc}"

        # 已有注释时，检查是否需要补充原始字段名
        existing_desc = field.get_description()
        if field.has_kdoc() and existing_desc:
            # 已有 KDoc 注释，检查原始字段名是否已在注释中
            if orig_name and orig_name != field.name and orig_name not in existing_desc:
                pass  # 需要更新，继续执行
            else:
                continue  # 注释已完整，跳过

        if dry_run:
            changes.append(f"  ~ {field.name} -> \"{comment_text}\"")
            continue

        # 标记要删除的旧注释行
        for j in range(field.line_idx - 1, -1, -1):
            s = info.all_lines[j].strip()
            if s.startswith('/**') or s.startswith('*/') or s.startswith('*') or s.startswith('/*') or s.startswith('//'):
                ops.append({"line": j, "action": "delete"})
            elif s == '' and ops and ops[-1]["action"] == "delete":
                ops.append({"line": j, "action": "delete"})
            else:
                break

        # 替换行尾注释行（移除 //fl 或 //xxx）
        ops.append({
            "line": field.line_idx,
            "action": "strip_inline_comment",
            "original_line": info.all_lines[field.line_idx],
        })

        # 提取缩进
        indent = ""
        m = re.match(r'^(\s*)', info.all_lines[field.line_idx])
        if m:
            indent = m.group(1)
        comment_line = f"{indent}/** {comment_text} */"

        # 在字段上方插入新注释
        ops.append({
            "line": field.line_idx,
            "action": "insert_before",
            "content": comment_line,
        })

        changes.append(f"  + {field.name} -> \"{comment_text}\"")

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
            if dry_run:
                changes.append(f"  ~ [class KDoc]")
            else:
                class_idx = info.class_start_idx
                for cl in reversed(new_kdoc.split('\n')):
                    ops.append({
                        "line": class_idx,
                        "action": "insert_before",
                        "content": cl,
                    })
                changes.append(f"  + [class KDoc]")

    if not changes or dry_run:
        return changes

    # --- 应用操作（按行号从大到小，同行同action按添加顺序反转） ---
    # 对同行的 insert_before，后添加的会出现在更前面，因此需将同类插入按添加逆序排列
    ops.sort(key=lambda o: o["line"], reverse=True)
    # 对连续同行的 insert_before，反转它们的相对顺序
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

    # --- 写入 ---
    content = '\n'.join(new_lines)
    if not content.endswith('\n'):
        content += '\n'
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return changes


def main():
    parser = argparse.ArgumentParser(
        description="根据 Swagger JSON 为 Kotlin Bean 类补充注释",
        epilog="示例:\n"
               "  %(prog)s --input https://example.com/v2/api-docs\n"
               "  %(prog)s --input swagger.json\n"
               "  %(prog)s --dry-run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, help="Swagger 数据源：api-docs URL 或本地 JSON 文件路径")
    parser.add_argument("--beans-dir", required=True, help="Kotlin Bean 类所在目录")
    parser.add_argument("--dry-run", "-n", action="store_true", help="只报告不写入")
    parser.add_argument("--check-only", action="store_true", help="CI 检查模式")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent

    # 找到项目根目录（向上查找 .git）
    project_root = script_dir
    while project_root != project_root.parent:
        if (project_root / ".git").exists():
            break
        project_root = project_root.parent

    beans_dir = project_root / args.beans_dir
    if not beans_dir.is_dir():
        print(f"ERROR: directory not found: {beans_dir}")
        sys.exit(1)

    # 第 1 步：加载 Swagger JSON
    swagger_path, is_temp = get_swagger_path(args.input)
    if not swagger_path or not swagger_path.is_file():
        print(f"ERROR: cannot load Swagger JSON from: {source}")
        sys.exit(1)

    # 第 2 步：解析 Swagger
    print(f"[parse] {swagger_path}")
    raw = load_swagger_json(str(swagger_path))
    swagger_map = build_swagger_map(raw)
    flat_map = get_flat_field_map(swagger_map)
    print(f"  definitions: {len(swagger_map) - 2}, flat fields: {len(flat_map)}")

    # 第 3 步：遍历 Kotlin 文件
    kt_files = sorted(beans_dir.rglob("*.kt"))
    print(f"[scan] {len(kt_files)} Kotlin files")

    total_changes = 0
    files_modified = 0

    for kt_file in kt_files:
        rel_path = kt_file.relative_to(project_root)
        changes = process_file(
            kt_file, flat_map, swagger_map,
            MANUAL_COMMENTS, dry_run=args.dry_run,
        )
        if changes:
            files_modified += 1
            total_changes += len(changes)
            print(f"\n  {rel_path}")
            for c in changes:
                print(c)

    print(f"\n{'='*60}")
    if args.dry_run:
        print(f"DRY-RUN: {files_modified} files, {total_changes} changes")
    else:
        print(f"DONE: {files_modified} files modified, {total_changes} changes")

    # 清理临时文件
    if is_temp and swagger_path and swagger_path.is_file():
        try:
            swagger_path.unlink()
        except Exception:
            pass

    if args.check_only and total_changes > 0:
        print("CI CHECK FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
