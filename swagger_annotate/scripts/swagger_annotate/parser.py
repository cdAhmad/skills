"""
Swagger JSON 解析模块。

核心策略：
- Swagger definitions 使用服务端原始类名（如 ApplyOrderResp），而 Kotlin 类名被 R8 混淆
- 但 Swagger property KEY 就是混淆后的字段名，与 Kotlin 字段名一致
- 因此通过「字段名集合重叠度」将 Swagger definition 匹配到 Kotlin class
"""

import json
import re
from pathlib import Path


def load_swagger_json(filepath: str) -> dict:
    """加载 Swagger JSON 文件，支持直接 JSON 和缓存包装格式。"""
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if "swaggerDoc" in raw:
        return raw["swaggerDoc"]
    if "swagger" in raw:
        return raw
    raise ValueError(f"无法识别的 Swagger JSON 格式: {filepath}")


def _parse_description(desc_raw: str) -> str:
    """
    解析 Swagger property description 字段。
    贪婪剥离左侧所有 "英文标识符:" 前缀，剩余部分即为中文描述。
    """
    if not desc_raw or not desc_raw.strip():
        return ""
    return _parse_raw(desc_raw)[1]


def _parse_raw(desc_raw: str) -> tuple[str, str]:
    """
    解析 Swagger property description 字段，返回 (原始字段名, 中文描述)。

    格式:
      "originalName:中文描述"
      "originalName:wireName:中文描述"  (多层前缀)
      "中文描述"                         (无前缀)

    原始字段名 = 第一个英文标识符（多层格式时是 Java 字段名，单层格式时=wire 名）
    中文描述   = 剥离所有英文标识符前缀后的剩余内容
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

    # 贪婪剥离所有英文标识符前缀
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

    # 过滤无意义结果
    if not text or text.strip().lower() in ("null", "null:"):
        return (original_name, "")

    return (original_name, text)


def get_original_name(desc_raw: str) -> str:
    """从 Swagger description 中提取混淆前的原始字段名。"""
    return _parse_raw(desc_raw)[0]


def build_flat_field_map(raw: dict) -> dict[str, tuple[str, str]]:
    """
    构建全局扁平映射：{property_name → (原始字段名, "中文描述")}。

    遍历所有 Swagger definitions 的所有 property，
    因为 property key 就是混淆后的字段名（与 Kotlin 一致）。
    如有重名冲突，取第一个（实际极少发生）。
    """
    definitions = raw.get("definitions", {})
    flat_map: dict[str, tuple[str, str]] = {}

    for _def_name, def_body in definitions.items():
        for prop_key, prop_body in def_body.get("properties", {}).items():
            if prop_key in flat_map:
                continue
            desc_raw = prop_body.get("description", "")
            orig, chinese = _parse_raw(desc_raw)
            if chinese:
                flat_map[prop_key] = (orig, chinese)

    return flat_map


def build_swagger_map(raw: dict) -> dict:
    """
    构建结构化映射，同时支持按 definition name 查找和按字段集匹配。

    返回:
        {
            "__flat__": {property_name → "中文描述"},          # 全局扁平映射
            "__by_fields__": {frozenset(field_names) → def_info}, # 字段集索引
            "DefinitionName": {                               # 按原始定义名索引
                "properties": {prop→desc},
                "path_info": {...},
            },
            ...
        }
    """
    definitions = raw.get("definitions", {})
    paths = raw.get("paths", {})

    # 构建 definition → 路径信息
    def_to_path_info = {}
    for path, methods in paths.items():
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            for param in op.get("parameters", []):
                schema = param.get("schema", {})
                ref = schema.get("$ref", "")
                if ref.startswith("#/definitions/"):
                    def_name = ref.split("/")[-1]
                    if def_name not in def_to_path_info:
                        def_to_path_info[def_name] = {
                            "path": path,
                            "method": method.upper(),
                            "tag": (op.get("tags") or ["Unknown"])[0],
                            "summary": op.get("summary", ""),
                        }
            for _status, resp in op.get("responses", {}).items():
                schema = resp.get("schema", {})
                ref = schema.get("$ref", "")
                if ref.startswith("#/definitions/"):
                    def_name = ref.split("/")[-1]
                    if def_name not in def_to_path_info:
                        def_to_path_info[def_name] = {
                            "path": path,
                            "method": method.upper(),
                            "tag": (op.get("tags") or ["Unknown"])[0],
                            "summary": op.get("summary", ""),
                        }
                items_ref = schema.get("items", {}).get("$ref", "")
                if items_ref.startswith("#/definitions/"):
                    def_name = items_ref.split("/")[-1]
                    if def_name not in def_to_path_info:
                        def_to_path_info[def_name] = {
                            "path": path,
                            "method": method.upper(),
                            "tag": (op.get("tags") or ["Unknown"])[0],
                            "summary": op.get("summary", ""),
                        }

    # 构建每个 definition 的属性映射
    result = {}
    flat_map: dict[str, tuple[str, str]] = {}
    by_fields: dict[frozenset, dict] = {}

    for def_name, def_body in definitions.items():
        props = {}
        for prop_key, prop_body in def_body.get("properties", {}).items():
            desc_raw = prop_body.get("description", "")
            orig, chinese = _parse_raw(desc_raw)
            if chinese:
                props[prop_key] = (orig, chinese)
                if prop_key not in flat_map:
                    flat_map[prop_key] = (orig, chinese)

        if not props:
            continue

        path_info = def_to_path_info.get(def_name)
        result[def_name] = {
            "properties": props,
            "path_info": path_info,
        }

        # 用字段名集合建立反向索引（用于匹配混淆类名）
        field_set = frozenset(props.keys())
        if field_set not in by_fields:
            by_fields[field_set] = result[def_name]

    result["__flat__"] = flat_map
    result["__by_fields__"] = by_fields

    return result


def match_class_to_definition(kotlin_field_names: list[str], swagger_map: dict) -> dict | None:
    """
    根据 Kotlin 类的字段名集合，在 Swagger definitions 中找到最佳匹配。

    匹配策略：
    1. 精确匹配字段集（frozenset 相等）→ 直接返回
    2. 找 Jaccard 相似度最高的 definition（阈值 >= 0.5）
    3. 若无匹配，返回 None
    """
    if not kotlin_field_names:
        return None

    by_fields = swagger_map.get("__by_fields__", {})
    kt_set = frozenset(kotlin_field_names)

    # 精确匹配
    if kt_set in by_fields:
        return by_fields[kt_set]

    # 模糊匹配：找字段重叠数最多的 definition
    best_match = None
    best_overlap = 0
    best_total = 1

    for field_set, def_info in by_fields.items():
        overlap = len(kt_set & field_set)
        if overlap > best_overlap:
            best_overlap = overlap
            best_total = len(field_set)
            best_match = def_info
        elif overlap == best_overlap and overlap > 0:
            # 重叠数相同时，选 Jaccard 相似度更高的
            current_jaccard = overlap / len(kt_set | field_set)
            best_jaccard = best_overlap / (len(kt_set) | best_total) if best_match else 0
            if current_jaccard > best_jaccard:
                best_overlap = overlap
                best_total = len(field_set)
                best_match = def_info

    # 需要足够高的覆盖率（至少覆盖 Kotlin 类 50% 的字段）
    if best_match and best_overlap >= len(kotlin_field_names) * 0.5:
        return best_match

    return None


def get_flat_field_map(swagger_map: dict) -> dict[str, tuple[str, str]]:
    """获取全局扁平字段→(原始字段名, 描述)映射。"""
    return swagger_map.get("__flat__", {})


def get_property_desc(flat_map: dict[str, tuple[str, str]], field_name: str) -> tuple[str, str]:
    """从扁平映射中查询字段的 (原始字段名, 中文描述)。"""
    return flat_map.get(field_name, ("", ""))


def get_class_path_info(matched_def: dict | None) -> dict | None:
    """获取匹配到的 definition 的路径信息。"""
    if matched_def:
        return matched_def.get("path_info")
    return None
