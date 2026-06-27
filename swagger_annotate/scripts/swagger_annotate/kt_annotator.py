"""
Kotlin Bean 文件解析与注释补充模块。
"""

import re
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class FieldInfo:
    """Kotlin 字段信息"""
    name: str
    type_str: str
    line_idx: int
    comment_lines_before: list[str] = field(default_factory=list)  # 字段上方注释行
    inline_comment: str = ""
    default_value: str = ""
    is_val: bool = False
    raw_line: str = ""

    def has_kdoc(self) -> bool:
        return any("/**" in c for c in self.comment_lines_before)

    def has_line_comment_before(self) -> bool:
        """是否有上方行注释 (// ...)"""
        return any(
            c.strip().startswith("//") and not c.strip().startswith("///")
            for c in self.comment_lines_before
        )

    def is_fl_placeholder(self) -> bool:
        return self.inline_comment.strip() == "fl" and not self.has_kdoc()

    def get_description(self) -> str:
        """提取现有注释中的语义描述文本"""
        for c in self.comment_lines_before:
            if "/**" in c:
                m = re.search(r'/\*\*\s*(.*?)\s*\*/', c)
                if m:
                    text = m.group(1).strip()
                    if text and not text.startswith("参数格式"):
                        return text
            if c.strip().startswith("//"):
                text = c.strip()[2:].strip()
                if text and text.lower() != "fl":
                    return text
        if self.inline_comment and self.inline_comment.strip().lower() != "fl":
            return self.inline_comment.strip()
        return ""

    def needs_fix(self) -> bool:
        if self.is_fl_placeholder():
            return True
        if self.has_line_comment_before() and not self.has_kdoc():
            return True
        if self.inline_comment and not self.has_kdoc() and self.inline_comment.strip().lower() != "fl":
            return True
        if not self.has_kdoc() and not self.has_line_comment_before() and not self.inline_comment:
            return True
        return False


@dataclass
class ClassInfo:
    file_path: Path
    package_name: str = ""
    class_name: str = ""
    class_kdoc: list[str] = field(default_factory=list)
    is_data_class: bool = True
    fields: list[FieldInfo] = field(default_factory=list)
    all_lines: list[str] = field(default_factory=list)
    class_start_idx: int = -1

    def needs_class_kdoc(self) -> bool:
        return len(self.class_kdoc) == 0


def parse_kotlin_file(filepath: Path) -> ClassInfo:
    """解析一个 Kotlin data class 文件。"""
    with open(filepath, "r", encoding="utf-8") as f:
        raw_lines = [l.rstrip('\n\r') for l in f.readlines()]

    info = ClassInfo(
        file_path=filepath,
        class_name=filepath.stem,
        all_lines=raw_lines,
    )

    # 提取 package
    for line in raw_lines:
        m = re.match(r'package\s+([\w.]+)', line)
        if m:
            info.package_name = m.group(1)
            break

    # 查找 data class 声明行
    class_start_idx = -1
    for i, line in enumerate(raw_lines):
        if re.match(r'\s*(data\s+)?(open\s+)?class\s+\w+', line):
            class_start_idx = i
            break

    if class_start_idx < 0:
        return info

    info.class_start_idx = class_start_idx

    m = re.search(r'class\s+(\w+)', raw_lines[class_start_idx])
    if m:
        info.class_name = m.group(1)
    info.is_data_class = 'data class' in raw_lines[class_start_idx]

    # 提取类 KDoc
    kdoc_lines = []
    j = class_start_idx - 1
    while j >= 0:
        stripped = raw_lines[j].strip()
        if stripped.endswith('*/') or stripped.startswith('*') or stripped.startswith('/**'):
            kdoc_lines.insert(0, stripped)
            if stripped.startswith('/**'):
                break
            j -= 1
        elif stripped == '' and kdoc_lines:
            j -= 1
            continue
        else:
            break
    if kdoc_lines and any('/**' in l for l in kdoc_lines):
        info.class_kdoc = kdoc_lines

    # 解析字段
    info.fields = _parse_fields(raw_lines, class_start_idx)

    return info


def _parse_fields(lines: list[str], class_start_idx: int) -> list[FieldInfo]:
    """从 data class 声明中解析字段列表。"""
    fields = []

    # 判断是否是单行类声明（括号在同一行闭合）
    class_line = lines[class_start_idx]
    single_line = _count_paren_diff(class_line) <= 0 and '(' in class_line

    if single_line:
        return _parse_single_line_fields(lines, class_start_idx)
    else:
        return _parse_multi_line_fields(lines, class_start_idx)


def _count_paren_diff(s: str) -> int:
    return s.count('(') - s.count(')')


def _parse_single_line_fields(lines: list[str], class_start_idx: int) -> list[FieldInfo]:
    """处理单行类声明，如 open class Foo(val a: Int?, val b: String?) {"""
    combined = " ".join(lines[class_start_idx].split('\n'))
    m = re.search(r'\((.*)\)', combined, re.DOTALL)
    if not m:
        return []
    body = m.group(1)
    field_strs = _split_fields(body)

    result = []
    for fs in field_strs:
        fs = fs.strip()
        fs = re.sub(r'\s*[){]\s*[{$]?\s*$', '', fs).strip()
        if not fs:
            continue
        fm = re.match(
            r'^\s*(?:(?:override|open|internal|private|protected|public)\s+)?'
            r'(var|val)\s+(\w+)\s*:\s*(.+?)(?:\s*=\s*([^,\n]*?))?\s*$',
            fs
        )
        if fm:
            result.append(FieldInfo(
                name=fm.group(2), type_str=fm.group(3).strip().rstrip(','),
                line_idx=class_start_idx,
                default_value=(fm.group(4) or "").strip(),
                is_val=(fm.group(1) == 'val'), raw_line=lines[class_start_idx],
            ))
    return result


def _parse_multi_line_fields(lines: list[str], class_start_idx: int) -> list[FieldInfo]:
    """逐行解析多行类声明中的字段。"""
    fields = []
    in_class = False
    paren_depth = 0
    pending_comments: list[str] = []

    for i in range(class_start_idx, len(lines)):
        stripped = lines[i].strip()

        if not in_class:
            if '(' in stripped:
                in_class = True
                paren_depth = _count_paren_diff(stripped)
                if paren_depth <= 0:
                    break
            continue

        paren_depth += _count_paren_diff(stripped)
        if paren_depth <= 0:
            break

        if not stripped:
            pending_comments = []
            continue

        # 收集注释行
        if stripped.startswith('/**') or stripped.startswith('*') or stripped.startswith('*/'):
            pending_comments.append(stripped)
            continue
        if stripped.startswith('//') and not stripped.startswith('///'):
            pending_comments.append(stripped)
            continue

        # 尝试匹配字段声明
        fm = re.match(
            r'^\s*(?:(?:override|open|internal|private|protected|public)\s+)?'
            r'(var|val)\s+'
            r'(\w+)\s*:\s*'
            r'(.+?)'
            r'(?:\s*=\s*([^,\n]*?))?'
            r'\s*,?\s*'
            r'(?://\s*(.*?))?\s*$',
            lines[i]
        )

        if fm:
            field_info = FieldInfo(
                name=fm.group(2),
                type_str=fm.group(3).strip().rstrip(','),
                line_idx=i,
                comment_lines_before=list(pending_comments),
                inline_comment=(fm.group(5) or "").strip(),
                default_value=(fm.group(4) or "").strip(),
                is_val=(fm.group(1) == 'val'),
                raw_line=lines[i],
            )
            fields.append(field_info)
            pending_comments = []

    return fields


def _split_fields(body: str) -> list[str]:
    """按逗号分割字段声明，正确处理泛型嵌套 <>."""
    parts = []
    depth = 0
    current = ""
    for ch in body:
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def generate_class_kdoc(path_info: dict | None = None, summary: str = "") -> str:
    """生成类级别 KDoc 注释。"""
    prefix = "接口参数对象"
    if path_info:
        path = path_info.get("path", "")
        tag = path_info.get("summary", summary)
        if tag:
            return f"/**\n * {prefix}：{tag}\n * 接口地址：{path}\n */"
        return f"/**\n * {prefix}\n * 接口地址：{path}\n */"
    return f"/** {prefix}：{summary} */" if summary else ""
