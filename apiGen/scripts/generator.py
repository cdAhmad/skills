"""Kotlin 代码生成器 — 从清洗后的 Swagger JSON 生成 kotlinx.serialization 模型 + Retrofit2 API"""

from __future__ import annotations

import json
import os
import re
from typing import Any

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


def _safe_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name[0].isdigit():
        name = "_" + name
    if name in _KOTLIN_KEYWORDS:
        name = "`%s`" % name
    return name


def _swagger_type_to_kotlin(param: dict, definitions: dict) -> str:
    if "$ref" in param:
        return _safe_name(param["$ref"].split("/")[-1])
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
               original_name: str = "", used_by: list[str] | None = None) -> str:
    safe_name = _safe_name(def_name)
    props = definition.get("properties", {})

    lines = [f"package {pkg}", "", "import kotlinx.serialization.SerialName",
             "import kotlinx.serialization.Serializable", ""]

    # 类注释：原始名 + 引用接口
    comments = []
    if original_name:
        comments.append(f"原始名: {original_name}")
    if used_by:
        comments.append("被以下接口引用:")
        comments.extend(f"  {u}" for u in used_by)
    if comments:
        lines.append("/**")
        for c in comments:
            lines.append(f" * {c}")
        lines.append(" */")

    lines.extend(["@Serializable", f"data class {safe_name}("])

    field_lines = []
    for prop_name, prop_schema in props.items():
        fname = _safe_name(prop_name)
        ktype = _swagger_type_to_kotlin(prop_schema, definitions)
        raw_desc = prop_schema.get("description", "")

        # 提取原始字段名 + 中文描述
        orig_name = prop_name
        cn_desc = ""
        if raw_desc and ":" in raw_desc:
            orig_name = raw_desc.split(":", 1)[0].strip()
            if raw_desc.count(":") >= 3:
                cn_desc = raw_desc.rsplit(":", 1)[-1].strip()

        comment = f"// {orig_name}"
        if cn_desc:
            comment += f" {cn_desc}"

        annot = f'@SerialName("{prop_name}") ' if fname != prop_name else ""
        nullable = "?"
        default = f" = {_default_value(ktype)}"

        field_lines.append(f"    {comment}")
        field_lines.append(f"    {annot}val {fname}: {ktype}{nullable}{default}")

    lines.append(",\n".join(field_lines))
    lines.append(")")
    return "\n".join(lines)


# ── API 接口 ─────────────────────────────────────────────────

def _gen_api(swagger: dict, pkg: str, model_pkg: str,
             base_response_name: str,
             common_headers: list[dict] | None = None,
             split_by_tag: bool = False, tag_info: dict | None = None,
             api_name: str = "ApiService"
             ) -> tuple[str, dict[str, list[str]]]:
    """生成 Retrofit2 API，返回 (代码, 模型使用映射)"""
    paths = swagger.get("paths", {})
    definitions = swagger.get("definitions", {})

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

            # 返回类型 — 优先选择 2xx 响应来确定泛型参数
            sorted_responses = sorted(responses.items(),
                                      key=lambda x: (0 if x[0].startswith("2") else 1, x[0]))
            return_type = f"{base_response_name}<kotlin.Any>"
            response_infos = []
            type_from_response = None
            for code, resp in sorted_responses:
                if not isinstance(resp, dict):
                    continue
                response_infos.append((code, resp.get("description", "")))
                if type_from_response is not None:
                    continue  # 已从更优先的响应码获取了类型
                schema = resp.get("schema", {})
                if "$ref" in schema:
                    ref = _safe_name(schema["$ref"].split("/")[-1])
                    type_from_response = f"{base_response_name}<{ref}>"
                    model_imports.add(ref)
                    model_usage.setdefault(ref, []).append(endpoint_desc)
                elif schema.get("type") == "array":
                    items = schema.get("items", {})
                    if "$ref" in items:
                        ref = _safe_name(items["$ref"].split("/")[-1])
                        type_from_response = f"{base_response_name}<kotlin.collections.List<{ref}>>"
                        model_imports.add(ref)
                        model_usage.setdefault(ref, []).append(endpoint_desc)
                    else:
                        inner = _swagger_type_to_kotlin(items, definitions)
                        type_from_response = f"{base_response_name}<kotlin.collections.List<{inner}>>"
            if type_from_response:
                return_type = type_from_response

            # 构建 Retrofit 注解和参数
            annotations = []
            retrofit_path = path
            for pp in path_params:
                retrofit_path = retrofit_path.replace(f"{{{pp['orig']}}}", f"{{{pp['name']}}}")

            has_form = any(p.get("in") in ("formData", "multipartFile") for p in params)
            has_body = body_param is not None

            if has_form:
                annotations.append("@Multipart")
            elif has_body:
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
                    func_params.append(
                        f'@Query("{qp["orig"]}") {qp["name"]}: {qp["type"]}? = null')
            for hp in header_params:
                if hp["required"]:
                    func_params.append(f'@Header("{hp["orig"]}") {hp["name"]}: {hp["type"]}')
                else:
                    func_params.append(
                        f'@Header("{hp["orig"]}") {hp["name"]}: {hp["type"]}? = null')
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

    # ── 构建代码 ──

    def _build_imports() -> list[str]:
        imps = [f"package {pkg}", "",
                f"import {model_pkg}.{base_response_name}",
                "import retrofit2.http.*", ""]
        if has_multipart:
            imps.extend(["import okhttp3.MultipartBody",
                         "import okhttp3.RequestBody", ""])
        for m in sorted(model_imports):
            imps.append(f"import {model_pkg}.{m}")
        return imps

    def _build_header_obj() -> list[str]:
        if not common_headers:
            return []
        h = ["", "object ApiHeaders {",
             "    @JvmStatic",
             "    fun createHeaders("]
        h_params = []
        for hdr in common_headers:
            hname = _safe_name(hdr["originalName"])
            htype = _SWAGGER_TO_KOTLIN.get(hdr.get("type", "string"), "kotlin.String")
            nullable = "?" if not hdr.get("required", False) else ""
            default = " = null" if not hdr.get("required", False) else ""
            h_params.append(f"        {hname}: {htype}{nullable}{default}")
        h.append(",\n".join(h_params))
        h.append("    ): kotlin.collections.Map<kotlin.String, kotlin.String> {")
        h.append("        return buildMap {")
        for hdr in common_headers:
            hname = _safe_name(hdr["originalName"])
            obf_name = hdr["name"]
            if hdr.get("required", False):
                h.append(f'            put("{obf_name}", {hname})')
            else:
                h.append(f"            if ({hname} != null) put(\"{obf_name}\", {hname})")
        h.append("        }")
        h.append("    }")
        h.append("}")
        return h

    def _build_methods(ops: list[dict]) -> list[str]:
        ml = []
        for op in ops:
            ml.append("    /**")
            if op["summary"]:
                ml.append(f"     * {op['summary']}")
            ml.append(f"     * {op['http_method']} {op['path']}")
            if op["response_infos"]:
                ml.append("     *")
                ml.append("     * Responses:")
                for code, desc in op["response_infos"]:
                    ml.append(f"     *   {code} - {desc}")
            ml.append("     */")
            for ann in op["annotations"]:
                ml.append(f"    {ann}")
            params_str = ",\n        ".join(op["func_params"])
            if params_str:
                params_str = "\n        " + params_str + "\n    "
            ml.append(f"    suspend fun {op['op_id']}({params_str}): {op['return_type']}")
            ml.append("")
        return ml

    lines = _build_imports()
    lines.append("")

    if split_by_tag and tag_info:
        # 构建反向映射: obfuscated_name → {description, original_name}
        tag_map: dict[str, dict] = {}
        for orig, info in tag_info.items():
            tag_map[info["obfuscated"]] = {"description": info["description"], "original": orig}

        # 按 tag 分组
        tag_ops: dict[str, list[dict]] = {}
        for m in all_methods:
            tag_ops.setdefault(m["tag"], []).append(m)

        for tag_name, ops in tag_ops.items():
            info = tag_map.get(tag_name, {})
            desc = info.get("description", "")
            lines.append("/**")
            if desc:
                lines.append(f" * {desc}")
            lines.append(" */")
            lines.append(f"interface {tag_name} {{")
            lines.append("")
            lines.extend(_build_methods(ops))
            lines.append("}")
            lines.append("")
    else:
        lines.append(f"interface {api_name} {{")
        lines.append("")
        lines.extend(_build_methods(all_methods))
        lines.append("}")

    lines.extend(_build_header_obj())
    return "\n".join(lines), model_usage


# ── 主生成入口 ───────────────────────────────────────────────

def generate(input_file: str, output_dir: str, package_name: str,
             model_package: str, api_package: str,
             base_response_name: str,
             common_headers: list[dict] | None = None,
             model_name_mapping: dict[str, str] | None = None,
             split_by_tag: bool = False, tag_info: dict | None = None,
             source_folder: str = "src/main/kotlin",
             api_name: str = "ApiService"):
    """从清洗后的 Swagger JSON 生成 Kotlin 项目"""
    with open(input_file, encoding="utf-8") as f:
        swagger = json.load(f)

    definitions = swagger.get("definitions", {})

    src_parts = tuple(source_folder.strip("/").split("/"))
    model_path = os.path.join(output_dir, *src_parts, *model_package.split("."))
    api_path = os.path.join(output_dir, *src_parts, *api_package.split("."))
    os.makedirs(model_path, exist_ok=True)
    os.makedirs(api_path, exist_ok=True)

    # BaseResponse
    with open(os.path.join(model_path, f"{base_response_name}.kt"), "w", encoding="utf-8") as f:
        f.write(_gen_base_response(model_package, base_response_name))
    print(f"Generated {model_path}/{base_response_name}.kt")

    # API → 收集模型使用信息
    api_code, model_usage = _gen_api(swagger, api_package, model_package,
                                     base_response_name, common_headers,
                                     split_by_tag, tag_info, api_name)
    api_filename = f"{api_name}.kt"
    with open(os.path.join(api_path, api_filename), "w", encoding="utf-8") as f:
        f.write(api_code)
    print(f"Generated {api_path}/{api_filename}")

    # 反向映射: obfuscated → original
    rev_mapping = {}
    if model_name_mapping:
        rev_mapping = {v: k for k, v in model_name_mapping.items()}

    # 模型
    count = 0
    for def_name, definition in definitions.items():
        safe = _safe_name(def_name)
        orig = rev_mapping.get(def_name, "")
        used = model_usage.get(def_name, model_usage.get(safe, []))
        code = _gen_model(model_package, def_name, definition, definitions,
                          original_name=orig, used_by=used)
        with open(os.path.join(model_path, f"{safe}.kt"), "w", encoding="utf-8") as f:
            f.write(code)
        count += 1

    print(f"Done: {count} models + {base_response_name} + API interface")
