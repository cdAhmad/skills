"""Kotlin 代码生成器 — 从清洗后的 Swagger JSON 生成 kotlinx.serialization 模型 + Retrofit2 API
字段注释采用 swagger_annotate 风格的单行 KDoc：/** originalName: 中文描述 */
"""

from __future__ import annotations

import hashlib
import os
import re

_SWAGGER_TO_KOTLIN = {
    "string": "kotlin.String", "integer": "kotlin.Int", "number": "kotlin.Double",
    "boolean": "kotlin.Boolean", "object": "kotlin.Any",
}
_KOTLIN_KEYWORDS = {
    "package", "import", "class", "interface", "object", "fun", "val", "var",
    "if", "else", "when", "for", "while", "do", "return", "true", "false",
    "null", "is", "in", "as", "data", "companion", "public", "private", "suspend",
    "Unit", "Any", "Nothing", "String", "Int", "Long", "Double", "Boolean",
}

# 模块级中文名→英文名映射（由 generate() 初始化）
_MODEL_NAMES: dict[str, str] = {}
_HASH_WARNINGS: list[str] = []


def _safe_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name[0].isdigit():
        name = "_" + name
    if name in _KOTLIN_KEYWORDS:
        name = "`%s`" % name
    return name


def _safe_model_name(name: str) -> str:
    """处理模型名。优先级：_MODEL_NAMES > 纯 ASCII > 哈希兜底。"""
    # 1. 查显式映射（--modelNames 或 KDoc 扫描）
    if name in _MODEL_NAMES:
        return _safe_name(_MODEL_NAMES[name])

    # 2. 纯 ASCII 直接使用
    if name.isascii() and not any(c in name for c in " \t\n\r"):
        return _safe_name(name)

    # 3. 哈希兜底
    h = hashlib.sha256(name.encode()).hexdigest()[:8]
    ascii_part = "".join(c for c in name if c.isascii() and c.isalnum())
    fallback = _safe_name(f"{ascii_part}_{h}") if ascii_part else f"Model_{h}"
    _HASH_WARNINGS.append(f"模型名 '{name}' 使用了自动名称 '{fallback}'，建议通过 --modelNames 指定")
    return fallback


def _scan_kdoc_mappings(model_dir: str) -> dict[str, str]:
    """扫描已有 .kt 文件，从类 KDoc 中提取 'Swagger 原始名: X' → 类名的映射。"""
    mappings: dict[str, str] = {}
    if not os.path.isdir(model_dir):
        return mappings
    for fname in os.listdir(model_dir):
        if not fname.endswith(".kt"):
            continue
        fpath = os.path.join(model_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        # 提取 KDoc 中的 "Swagger 原始名: X"
        m = re.search(r'Swagger 原始名:\s*(\S.*?)(?:\n|$)', content)
        if not m:
            continue
        original_name = m.group(1).strip()
        # 提取类名
        cls_match = re.search(r'data class\s+(\w+)', content)
        if cls_match and original_name:
            mappings[original_name] = cls_match.group(1)
    return mappings


def _swagger_type_to_kotlin(param: dict, definitions: dict) -> str:
    if "$ref" in param:
        ref_name = param["$ref"].split("/")[-1]
        return _safe_model_name(ref_name)
    if "schema" in param:
        return _swagger_type_to_kotlin(param["schema"], definitions)
    stype = param.get("type", "object")
    if stype == "array":
        items = param.get("items", {})
        return f"kotlin.collections.List<{_swagger_type_to_kotlin(items, definitions)}>"
    if stype == "file":
        return "okhttp3.MultipartBody.Part"
    return _SWAGGER_TO_KOTLIN.get(stype, "kotlin.Any")


def _default_value(ktype: str) -> str:
    return "null"


# ── Description 解析（仿照 swagger_annotate 的 _parse_raw）──

def _parse_raw(desc_raw: str) -> tuple[str, str]:
    """解析 Swagger property description 字段，返回 (原始字段名, 中文描述)。

    格式:
      "originalName:中文描述"
      "originalName:wireName:中文描述"
      "中文描述"
    """
    text = desc_raw.strip()
    if not text:
        return ("", "")

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

    if not text or text.strip().lower() in ("null", "null:"):
        return (original_name, "")

    return (original_name, text)


# ── BaseResponse ─────────────────────────────────────────────

def _gen_base_response(pkg: str, name: str) -> str:
    return f"""package {pkg}

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class {name}<T>(
    @SerialName("code") val code: kotlin.Int? = null,
    @SerialName("msg") val msg: kotlin.String? = null,
    @SerialName("data") val `data`: T? = null,
)
"""


# ── 模型 ─────────────────────────────────────────────────────

def _gen_model(pkg: str, def_name: str, definition: dict, definitions: dict,
               used_by: list[str] | None = None) -> str:
    safe_name = _safe_model_name(def_name)
    props = definition.get("properties", {})

    lines = [f"package {pkg}", "", "import kotlinx.serialization.SerialName",
             "import kotlinx.serialization.Serializable", ""]

    # 类 KDoc：原始名 + 引用接口
    comments = []
    if def_name != safe_name:
        comments.append(f"Swagger 原始名: {def_name}")
    if used_by:
        comments.append("被以下接口引用:")
        comments.extend(f"  {u}" for u in used_by)
    if comments:
        lines.append("/**")
        for c in comments:
            lines.append(f" * {c}")
        lines.append(" */")

    lines.extend(["@Serializable", f"data class {safe_name}("])

    field_blocks = []
    for prop_name, prop_schema in props.items():
        fname = _safe_name(prop_name)
        ktype = _swagger_type_to_kotlin(prop_schema, definitions)
        raw_desc = prop_schema.get("description", "")

        # 解析 Swagger description → (原始字段名, 中文描述)
        orig_name, cn_desc = _parse_raw(raw_desc)

        # 生成 /** ... */ 风格注释（仿照 swagger_annotate）
        if orig_name and orig_name != fname:
            comment_text = f"{orig_name}: {cn_desc}" if cn_desc else orig_name
        else:
            comment_text = cn_desc if cn_desc else prop_name

        annot = f'@SerialName("{prop_name}") ' if fname != prop_name else ""
        nullable = "?"
        default = f" = {_default_value(ktype)}"

        field_blocks.append(f"    /** {comment_text} */\n    {annot}val {fname}: {ktype}{nullable}{default}")

    lines.append(",\n".join(field_blocks))
    lines.append(")")
    return "\n".join(lines)


# ── API 接口（公共逻辑）────────────────────────────────────

def _collect_operations(swagger: dict, base_response_name: str,
                        definitions: dict) -> tuple[list[dict], set[str], dict[str, list[str]], bool]:
    """遍历所有 paths，解析操作为统一结构。返回 (methods, model_imports, model_usage, has_multipart)。"""
    paths = swagger.get("paths", {})
    model_imports: set[str] = set()
    all_methods: list[dict] = []
    model_usage: dict[str, list[str]] = {}
    has_multipart = False

    for path, methods_dict in paths.items():
        for method, operation in methods_dict.items():
            if not isinstance(operation, dict):
                continue
            op_id = _safe_name(operation.get("operationId", "unknown"))
            summary = operation.get("summary", "")
            op_tags = operation.get("tags", ["Default"])
            op_tag = op_tags[0] if op_tags else "Default"
            endpoint_desc = f"{method.upper()} {path}"
            if summary:
                endpoint_desc += f" - {summary}"
            params = operation.get("parameters", [])
            responses = operation.get("responses", {})

            query_params, path_params, header_params = [], [], []
            body_param = None
            multipart_params = []

            for p in params:
                pin = p.get("in", "")
                pname = _safe_name(p.get("name", "unknown"))
                ktype = _swagger_type_to_kotlin(p, definitions)
                preq = p.get("required", False)

                if pin == "query":
                    query_params.append({"name": pname, "orig": p.get("name", ""),
                                         "type": ktype, "required": preq})
                elif pin == "path":
                    path_params.append({"name": pname, "orig": p.get("name", ""), "type": ktype})
                elif pin == "header":
                    header_params.append({"name": pname, "orig": p.get("name", ""),
                                          "type": ktype, "required": preq})
                elif pin == "body":
                    body_param = {"name": pname, "type": ktype}
                    if ktype not in ("kotlin.Any",) and not ktype.startswith("kotlin."):
                        model_imports.add(ktype)
                        model_usage.setdefault(ktype, []).append(endpoint_desc)
                elif pin in ("formData", "multipartFile"):
                    has_multipart = True
                    if pin == "multipartFile":
                        multipart_params.append(f"@Part {pname}: okhttp3.MultipartBody.Part")
                    else:
                        multipart_params.append(
                            f'@Part("{p.get("name","")}") {pname}: okhttp3.RequestBody')

            # 返回类型 — 优先选择 2xx 响应
            sorted_responses = sorted(responses.items(),
                                      key=lambda x: (0 if x[0].startswith("2") else 1, x[0]))
            return_type = f"{base_response_name}<kotlin.Any>"
            response_infos = []
            for code, resp in sorted_responses:
                if not isinstance(resp, dict):
                    continue
                response_infos.append((code, resp.get("description", "")))
                if return_type != f"{base_response_name}<kotlin.Any>":
                    continue  # 已从更优先的响应码获取了类型
                schema = resp.get("schema", {})
                if "$ref" in schema:
                    ref = _safe_model_name(schema["$ref"].split("/")[-1])
                    return_type = f"{base_response_name}<{ref}>"
                    model_imports.add(ref)
                    model_usage.setdefault(ref, []).append(endpoint_desc)
                elif schema.get("type") == "array":
                    items = schema.get("items", {})
                    if "$ref" in items:
                        ref = _safe_model_name(items["$ref"].split("/")[-1])
                        return_type = f"{base_response_name}<kotlin.collections.List<{ref}>>"
                        model_imports.add(ref)
                        model_usage.setdefault(ref, []).append(endpoint_desc)
                    else:
                        inner = _swagger_type_to_kotlin(items, definitions)
                        return_type = f"{base_response_name}<kotlin.collections.List<{inner}>>"

            # 构建 Retrofit 注解和参数
            annotations = []
            retrofit_path = path
            for pp in path_params:
                retrofit_path = retrofit_path.replace(f"{{{pp['orig']}}}", f"{{{pp['name']}}}")

            has_form = any(p.get("in") in ("formData", "multipartFile") for p in params)
            if has_form:
                annotations.append("@Multipart")
            elif body_param is not None:
                annotations.append('@Headers("Content-Type: application/json")')

            RETROFIT_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
            if method.upper() in RETROFIT_METHODS:
                annotations.append(f'@{method.upper()}("{retrofit_path}")')
            else:
                annotations.append(f'@HTTP(method = "{method.upper()}", path = "{retrofit_path}")')

            func_params = []
            for pp in path_params:
                func_params.append(f'@Path("{pp["name"]}") {pp["name"]}: {pp["type"]}')
            for qp in query_params:
                if qp["required"]:
                    func_params.append(f'@Query("{qp["orig"]}") {qp["name"]}: {qp["type"]}')
                else:
                    func_params.append(f'@Query("{qp["orig"]}") {qp["name"]}: {qp["type"]}? = null')
            for hp in header_params:
                if hp["required"]:
                    func_params.append(f'@Header("{hp["orig"]}") {hp["name"]}: {hp["type"]}')
                else:
                    func_params.append(f'@Header("{hp["orig"]}") {hp["name"]}: {hp["type"]}? = null')
            if body_param:
                func_params.append(f"@Body {body_param['name']}: {body_param['type']}")
            for mp in multipart_params:
                func_params.append(mp)

            all_methods.append(dict(
                op_id=op_id, summary=summary, annotations=annotations,
                func_params=func_params, return_type=return_type,
                http_method=method.upper(), path=path,
                response_infos=response_infos, tag=op_tag,
            ))

    return all_methods, model_imports, model_usage, has_multipart


def _render_interface(pkg: str, model_pkg: str, base_response_name: str,
                      model_imports: set[str], has_multipart: bool,
                      ops: list[dict], interface_name: str,
                      common_headers: list[dict] | None = None,
                      tag_desc: str = "") -> str:
    """渲染单个 Retrofit2 接口文件。"""
    imps = [f"package {pkg}", "",
            f"import {model_pkg}.{base_response_name}",
            "import retrofit2.http.*", ""]
    if has_multipart:
        imps.extend(["import okhttp3.MultipartBody",
                     "import okhttp3.RequestBody", ""])
    for m in sorted(model_imports):
        imps.append(f"import {model_pkg}.{m}")

    lines = imps + [""]

    if tag_desc:
        lines.append("/**")
        lines.append(f" * {tag_desc}")
        lines.append(" */")
    lines.append(f"interface {_safe_name(interface_name)} {{")
    lines.append("")

    for op in ops:
        lines.append("    /**")
        if op["summary"]:
            lines.append(f"     * {op['summary']}")
        lines.append(f"     * {op['http_method']} {op['path']}")
        if op["response_infos"]:
            lines.append("     *")
            lines.append("     * Responses:")
            for code, desc in op["response_infos"]:
                lines.append(f"     *   {code} - {desc}")
        lines.append("     */")
        for ann in op["annotations"]:
            lines.append(f"    {ann}")
        params_str = ",\n        ".join(op["func_params"])
        if params_str:
            params_str = "\n        " + params_str + "\n    "
        lines.append(f"    suspend fun {op['op_id']}({params_str}): {op['return_type']}")
        lines.append("")
    lines.append("}")

    # ApiHeaders
    if common_headers:
        lines.append("")
        lines.append("object ApiHeaders {")
        lines.append("    @JvmStatic")
        lines.append("    fun createHeaders(")
        h_params = []
        for hdr in common_headers:
            hname = _safe_name(hdr["originalName"])
            htype = _SWAGGER_TO_KOTLIN.get(hdr.get("type", "string"), "kotlin.String")
            nullable = "?" if not hdr.get("required", False) else ""
            default = " = null" if not hdr.get("required", False) else ""
            h_params.append(f"        {hname}: {htype}{nullable}{default}")
        lines.append(",\n".join(h_params))
        lines.append("    ): kotlin.collections.Map<kotlin.String, kotlin.String> {")
        lines.append("        return buildMap {")
        for hdr in common_headers:
            hname = _safe_name(hdr["originalName"])
            obf_name = hdr["name"]
            if hdr.get("required", False):
                lines.append(f'            put("{obf_name}", {hname})')
            else:
                lines.append(f"            if ({hname} != null) put(\"{obf_name}\", {hname})")
        lines.append("        }")
        lines.append("    }")
        lines.append("}")

    return "\n".join(lines)


def _gen_api(swagger: dict, pkg: str, model_pkg: str,
             base_response_name: str,
             common_headers: list[dict] | None = None,
             split_by_tag: bool = False, tag_info: dict | None = None,
             ) -> tuple[str, dict[str, list[str]]]:
    """生成 Retrofit2 API，返回 (代码, 模型使用映射)。"""
    definitions = swagger.get("definitions", {})
    all_methods, model_imports, model_usage, has_multipart = \
        _collect_operations(swagger, base_response_name, definitions)

    if split_by_tag and tag_info:
        parts = []
        tag_ops: dict[str, list[dict]] = {}
        for m in all_methods:
            tag_ops.setdefault(m["tag"], []).append(m)
        for tag_name, ops in tag_ops.items():
            info = tag_info.get(tag_name, {})
            parts.append(_render_interface(pkg, model_pkg, base_response_name,
                                           model_imports, has_multipart,
                                           ops, tag_name, common_headers,
                                           tag_desc=info.get("description", "")))
        return "\n".join(parts), model_usage

    code = _render_interface(pkg, model_pkg, base_response_name,
                             model_imports, has_multipart,
                             all_methods, "ApiService", common_headers)
    return code, model_usage


# ── 主生成入口 ───────────────────────────────────────────────

def generate(swagger: dict, output_dir: str, package_name: str,
             model_package: str, api_package: str,
             base_response_name: str,
             common_headers: list[dict] | None = None,
             split_by_tag: bool = False, tag_info: dict | None = None,
             source_folder: str = "src/main/kotlin",
             model_names: dict[str, str] | None = None):
    """从清洗后的 Swagger JSON 生成 Kotlin 项目（增量合并）"""
    global _MODEL_NAMES, _HASH_WARNINGS
    _HASH_WARNINGS = []

    # 初始化模型名映射：--modelNames > KDoc 扫描
    _MODEL_NAMES = dict(model_names) if model_names else {}

    definitions = swagger.get("definitions", {})

    src_parts = tuple(source_folder.strip("/").split("/"))
    model_path = os.path.join(output_dir, *src_parts, *model_package.split("."))
    api_path = os.path.join(output_dir, *src_parts, *api_package.split("."))
    os.makedirs(model_path, exist_ok=True)
    os.makedirs(api_path, exist_ok=True)

    # 从已有 .kt 文件的 KDoc 中恢复映射（优先级低于显式 --modelNames）
    kdoc_mappings = _scan_kdoc_mappings(model_path)
    for k, v in kdoc_mappings.items():
        if k not in _MODEL_NAMES:
            _MODEL_NAMES[k] = v

    # ── 辅助函数：纯增量追加 ──

    def _parse_field_names_from_code(code: str) -> set[str]:
        m = re.search(r'data class \w+\((.*)\)', code, re.DOTALL)
        if not m:
            return set()
        return set(re.findall(r'(?:val|var)\s+(\w+)\s*:', m.group(1)))

    def _parse_field_names_from_file(path: str) -> set[str]:
        with open(path, encoding="utf-8") as f:
            return _parse_field_names_from_code(f.read())

    def _append_model_fields(path: str, new_code: str):
        """在模型文件 ) 前追加 Swagger 新增字段"""
        new_fields_code = re.search(r'data class \w+\((.*)\)', new_code, re.DOTALL)
        if not new_fields_code:
            return
        old_names = _parse_field_names_from_file(path)
        # 提取新代码中所有字段块（/** 注释 + 可选注解 + val 声明）
        all_new = re.findall(
            r'(\s*/\*\*.*?\*/\n\s*(?:@\w+[^\n]*\n\s*)?val\s+\w+\s*:[^\n]*)',
            new_fields_code.group(1))
        added = []
        for f in all_new:
            f = f.strip().rstrip(',')
            name_match = re.search(r'val\s+(\w+)\s*:', f)
            if name_match and name_match.group(1) not in old_names:
                added.append(f)
        if not added:
            return
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == ")":
                # 前一行补逗号
                prev = lines[i-1].rstrip()
                if not prev.endswith(','):
                    lines[i-1] = prev + ',\n'
                for field in added:
                    lines.insert(i, f"    {field},\n")
                break
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def _parse_api_methods(code: str) -> set[str]:
        return set(re.findall(r'suspend fun\s+(\w+)\(', code))

    def _append_api_methods(path: str, new_code: str):
        """在 API 接口 } 前追加新方法 + 补充 import"""
        old_text = open(path, encoding="utf-8").read()
        old_methods = _parse_api_methods(old_text)

        # 补充 import: 新代码中有但旧文件没有的 model import
        pkg_prefix = f"import {model_package}."
        new_imports = set(re.findall(rf'^{pkg_prefix}\S+', new_code, re.MULTILINE))
        old_imports = set(re.findall(rf'^{pkg_prefix}\S+', old_text, re.MULTILINE))
        missing = sorted(new_imports - old_imports)
        if missing:
            lines = old_text.splitlines(keepends=True)
            insert_pos = 0
            for idx, l in enumerate(lines):
                if l.strip().startswith("import "):
                    insert_pos = idx + 1
            for imp in missing:
                lines.insert(insert_pos, imp + "\n")
                insert_pos += 1
            lines.insert(insert_pos, "\n")
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)

        # 提取新代码中 interface body 部分
        m = re.search(r'interface \w+ \{(.*)\}', new_code, re.DOTALL)
        if not m:
            return
        body = m.group(1)
        # 按方法块分割
        blocks = re.split(r'\n(?=    (?:/\*\*|@(?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|HTTP|Headers|Multipart|FormUrlEncoded|Streaming)\b))', body)
        merged = []
        buf = ""
        for block in blocks:
            b = block.rstrip()
            if not b:
                continue
            if 'suspend fun' in b:
                merged.append((buf + "\n" + b).lstrip('\n') if buf else b)
                buf = ""
            else:
                buf = (buf + "\n" + b).lstrip('\n') if buf else b
        # 筛选仅新增方法
        added = []
        for m_block in merged:
            name_match = re.search(r'suspend fun\s+(\w+)\(', m_block)
            if name_match and name_match.group(1) not in old_methods:
                added.append(m_block)
        if not added:
            return
        lines = open(path, encoding="utf-8").readlines()
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "}":
                for method in added:
                    for ml in reversed(method.split('\n')):
                        lines.insert(i, ml + "\n")
                    lines.insert(i, "\n")
                break
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    # BaseResponse — 始终全量（简单文件）
    br_file = f"{base_response_name}.kt"
    br_path = os.path.join(model_path, br_file)
    br_code = _gen_base_response(model_package, base_response_name)
    if os.path.exists(br_path):
        print(f"[skipped] {model_path}/{br_file}")
    else:
        with open(br_path, "w", encoding="utf-8") as f:
            f.write(br_code)
        print(f"[generated] {model_path}/{br_file}")

    # 收集操作信息（只做一次，不分 tag 模式也复用）
    all_methods, model_imports, model_usage, has_multipart = \
        _collect_operations(swagger, base_response_name, definitions)

    if split_by_tag and tag_info:
        # 按 tag 拆分：每个 tag 一个接口文件
        tag_ops: dict[str, list[dict]] = {}
        for m in all_methods:
            tag_ops.setdefault(m["tag"], []).append(m)

        for tag_name in tag_info:
            safe_tag = _safe_name(tag_name)
            api_file = f"{safe_tag}.kt"
            api_path_full = os.path.join(api_path, api_file)
            ops = tag_ops.get(tag_name, [])
            info = tag_info.get(tag_name, {})
            single_tag_code = _render_interface(
                api_package, model_package, base_response_name,
                model_imports, has_multipart, ops, tag_name,
                common_headers, tag_desc=info.get("description", ""))

            if os.path.exists(api_path_full):
                old_methods = _parse_api_methods(open(api_path_full, encoding="utf-8").read())
                new_methods = _parse_api_methods(single_tag_code)
                added = new_methods - old_methods
                if added:
                    _append_api_methods(api_path_full, single_tag_code)
                    print(f"[updated] +{len(added)} methods {api_path}/{api_file}")
                else:
                    print(f"[skipped] {api_path}/{api_file}")
            else:
                with open(api_path_full, "w", encoding="utf-8") as f:
                    f.write(single_tag_code)
                print(f"[generated] {api_path}/{api_file}")
    else:
        api_code = _render_interface(api_package, model_package, base_response_name,
                                     model_imports, has_multipart,
                                     all_methods, "ApiService", common_headers)
        api_file = "ApiService.kt"
        api_path_full = os.path.join(api_path, api_file)
        if os.path.exists(api_path_full):
            old_methods = _parse_api_methods(open(api_path_full, encoding="utf-8").read())
            new_methods = _parse_api_methods(api_code)
            added = new_methods - old_methods
            if added:
                _append_api_methods(api_path_full, api_code)
                print(f"[updated] +{len(added)} methods {api_path}/{api_file}")
            else:
                print(f"[skipped] {api_path}/{api_file}")
        else:
            with open(api_path_full, "w", encoding="utf-8") as f:
                f.write(api_code)
            print(f"[generated] {api_path}/{api_file}")

    # 模型 — 纯增量追加
    model_stats = {"new": 0, "updated": 0, "skipped": 0}
    for def_name, definition in definitions.items():
        safe = _safe_model_name(def_name)
        used = model_usage.get(safe, [])
        new_code = _gen_model(model_package, def_name, definition, definitions, used_by=used)
        model_file = os.path.join(model_path, f"{safe}.kt")
        if os.path.exists(model_file):
            old_names = _parse_field_names_from_file(model_file)
            new_names = _parse_field_names_from_code(new_code)
            added = new_names - old_names
            if added:
                _append_model_fields(model_file, new_code)
                model_stats["updated"] += 1
                print(f"[updated] +{len(added)} fields {safe}.kt")
            else:
                model_stats["skipped"] += 1
        else:
            with open(model_file, "w", encoding="utf-8") as f:
                f.write(new_code)
            model_stats["new"] += 1
            print(f"[generated] {model_path}/{safe}.kt")

    total = len(definitions)
    print(f"Done: {total} models ({model_stats['new']} new / {model_stats['updated']} updated / {model_stats['skipped']} skipped)")

    # 打印哈希兜底警告（去重）
    if _HASH_WARNINGS:
        print()
        seen = set()
        for w in _HASH_WARNINGS:
            if w not in seen:
                seen.add(w)
                print(f"⚠ {w}")
        print("提示: Agent 可通过 --modelNames \"原始名:英文名,...\" 指定可读的类名")
