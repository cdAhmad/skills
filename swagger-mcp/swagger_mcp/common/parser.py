"""Swagger description 字段解析 — 提取原始字段名和中文描述。

合并自:
- swagger-generate-interface/scripts/generator.py (_parse_raw)
- swagger_annotate/scripts/swagger_annotate/parser.py (_parse_raw)

格式约定:
  "originalName:中文描述"
  "originalName:wireName:中文描述"  (多层前缀)
  "中文描述"                         (无前缀)
"""

from __future__ import annotations

import re


def parse_field_desc(desc_raw: str) -> tuple[str, str]:
    """解析 Swagger property description，返回 (原始字段名, 中文描述)。

    >>> parse_field_desc("userName:用户姓名")
    ('userName', '用户姓名')
    >>> parse_field_desc("userName:a:用户姓名")
    ('userName', '用户姓名')
    >>> parse_field_desc("用户姓名")
    ('', '用户姓名')
    """
    text = desc_raw.strip()
    if not text:
        return ("", "")

    # 提取第一个英文标识符作为原始字段名
    original_name = ""
    if ":" in text:
        first_colon = text.index(":")
        first_left = text[:first_colon].strip()
        if re.match(r'^[a-zA-Z_]\w*$', first_left):
            original_name = first_left

    # 贪婪剥离所有英文标识符前缀，剩余为中文描述
    while ":" in text:
        colon_idx = text.index(":")
        left = text[:colon_idx].strip()
        right = text[colon_idx + 1:].strip()
        if re.match(r'^[a-zA-Z_]\w*$', left) and right:
            text = right
        elif re.match(r'^[a-zA-Z_]\w*$', left) and not right:
            text = ""
            break
        else:
            break

    if not text or text.strip().lower() in ("null", "null:"):
        return (original_name, "")

    return (original_name, text)
