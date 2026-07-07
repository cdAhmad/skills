"""Swagger JSON 清洗器 — 只做清洗不做混淆，内存管道（dict in → dict out）"""

from __future__ import annotations

from copy import deepcopy


class SwaggerCleaner:
    """清洗 Swagger JSON：剥离包装器、过滤响应码、收集公共 header、处理 tag。
    不混淆任何名称——模型名/方法名/Tag 名保持 Swagger 原文。"""

    def __init__(self, split_by_tag: bool = False):
        self.split_by_tag = split_by_tag
        self.common_headers: list[dict] = []
        self.tag_info: dict[str, dict] = {}  # tag_name → {description}

    # ── JSON 辅助 ─────────────────────────────────────────────

    @staticmethod
    def _deep_remove_key(obj, key: str):
        """递归删除 obj 中所有 key 属性"""
        if isinstance(obj, dict):
            obj.pop(key, None)
            for v in obj.values():
                SwaggerCleaner._deep_remove_key(v, key)
        elif isinstance(obj, list):
            for item in obj:
                SwaggerCleaner._deep_remove_key(item, key)

    # ── 清洗流程 ──────────────────────────────────────────────

    def clean(self, swagger: dict) -> dict | None:
        """主流程：深拷贝 → 清洗 → 返回清洗后的 dict。失败返回 None。"""
        try:
            swagger = deepcopy(swagger)
        except Exception as e:
            print(f"Error: failed to copy swagger JSON: {e}")
            return None

        # 步骤 1：移除 header 参数 + 修复 query 参数类型 + 收集公共 headers
        VALID_TYPES = {"string", "number", "integer", "boolean", "array", "object"}
        header_counts: dict[str, dict] = {}
        total_ops = 0

        for path, methods in swagger.get("paths", {}).items():
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                total_ops += 1
                params = operation.get("parameters", [])
                if isinstance(params, list):
                    new_params = []
                    for param in params:
                        if param.get("in") == "header":
                            hname = param.get("name", "")
                            desc = param.get("description", "")
                            parts = desc.split(":", 1) if desc else [hname, ""]
                            orig_name = parts[0].strip() if parts else hname
                            chinese_desc = desc.split(":")[-1].strip() if ":" in desc else ""
                            if hname not in header_counts:
                                header_counts[hname] = {
                                    "name": hname,
                                    "originalName": orig_name,
                                    "description": chinese_desc,
                                    "type": param.get("type", "string"),
                                    "required": param.get("required", False),
                                    "count": 0,
                                }
                            header_counts[hname]["count"] += 1
                            continue
                        if "name" not in param:
                            param["name"] = param.get("in", "unknown")
                        if param.get("in") == "query" and param.get("type", "string") not in VALID_TYPES:
                            old_type = param.get("type", "")
                            param["type"] = "string"
                            desc = param.get("description", "")
                            param["description"] = f"{desc} (原类型: {old_type})" if desc else f"原类型: {old_type}"
                        new_params.append(param)
                    operation["parameters"] = new_params

        # 公共 header：出现率 >= 90%
        self.common_headers = sorted(
            [h for h in header_counts.values() if h["count"] >= total_ops * 0.9],
            key=lambda h: (not h["required"], h["name"])
        )

        # 步骤 1.1：处理 tags（使用原始 tag 名，不混淆）
        swagger_tags = {t["name"]: t.get("description", "") for t in swagger.get("tags", [])}
        for path, methods in swagger.get("paths", {}).items():
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue

                if self.split_by_tag:
                    original_tags = operation.get("tags", ["Default"])
                    for t in original_tags:
                        if t not in self.tag_info:
                            self.tag_info[t] = {
                                "description": swagger_tags.get(t, ""),
                            }
                else:
                    operation["tags"] = ["ApiService"]

        # 步骤 2：剥离响应包装器（code/msg/data 模式）
        definitions = swagger.get("definitions", {})
        wrapper_models = set()
        wrapper_data_refs: dict[str, dict] = {}

        for def_name, def_schema in definitions.items():
            props = def_schema.get("properties", {})
            if "code" in props and "msg" in props:
                wrapper_models.add(def_name)
                data_prop = props.get("data")
                if data_prop:
                    wrapper_data_refs[def_name] = data_prop
                else:
                    wrapper_data_refs[def_name] = {"type": "object"}

        for path, methods in swagger.get("paths", {}).items():
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                for code, response in operation.get("responses", {}).items():
                    if not isinstance(response, dict):
                        continue
                    ref = response.get("$ref", response.get("schema", {}).get("$ref", ""))
                    if not ref:
                        continue
                    for wname in wrapper_models:
                        if f"/{wname}" in ref:
                            data_schema = wrapper_data_refs[wname]
                            response.pop("$ref", None)
                            if "schema" in response:
                                response["schema"].pop("$ref", None)
                            if "schema" not in response:
                                response["schema"] = {}
                            ref_target = data_schema.get("$ref", data_schema.get("originalRef", ""))
                            if ref_target:
                                response["schema"]["$ref"] = ref_target
                            elif "type" in data_schema:
                                response["schema"]["type"] = data_schema["type"]
                                if "items" in data_schema:
                                    response["schema"]["items"] = data_schema["items"]
                            else:
                                response["schema"]["type"] = "object"
                            break

        for wname in wrapper_models:
            definitions.pop(wname, None)

        # 步骤 3：移除 originalRef
        self._deep_remove_key(swagger, "originalRef")

        # 步骤 4：过滤非标准 HTTP 响应码
        for path, methods in swagger.get("paths", {}).items():
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                responses = operation.get("responses", {})
                filtered = {}
                for code, response in responses.items():
                    try:
                        code_int = int(code)
                        if 100 <= code_int <= 599:
                            if isinstance(response, dict) and "schema" not in response:
                                response["schema"] = {"type": "object"}
                            filtered[code] = response
                        else:
                            if "description" in response:
                                operation["description"] = (operation.get("description", "") +
                                                            f"\n[响应 {code}]: {response['description']}")
                    except ValueError:
                        filtered[code] = response
                operation["responses"] = filtered

        return swagger
