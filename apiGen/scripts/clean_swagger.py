"""Swagger JSON 清洗与混淆 — 与 api_gen 的 CleanSwaggerScript 等价"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy


class CleanSwaggerScript:
    def __init__(self, salt: str, api_name: str = "Default",
                 obfuscate_operation_id: bool = True,
                 model_name_map: dict[str, str] | None = None,
                 export_model_mapping_file: str | None = None,
                 export_common_headers_file: str | None = None,
                 split_by_tag: bool = False):
        self.salt = salt
        self.api_name = api_name
        self.obfuscate_operation_id = obfuscate_operation_id
        self.model_name_map = model_name_map or {}
        self.export_model_mapping_file = export_model_mapping_file
        self.export_common_headers_file = export_common_headers_file
        self.split_by_tag = split_by_tag
        self._new_mappings: dict[str, str] = {}
        self.common_headers: list[dict] = []
        self.tag_info: dict[str, dict] = {}  # tag_name → {obfuscated_name, description}

    # ── 哈希生成 ──────────────────────────────────────────────

    def _generate_field_name(self, original: str) -> str:
        """用 SHA-256 + salt 生成 12-20 位的 PascalCase 混淆名"""
        if not self.salt:
            raise ValueError("salt must not be blank")
        input_str = original + self.salt
        hash_bytes = hashlib.sha256(input_str.encode()).digest()

        # 前 4 字节作为长度种子
        seed = int.from_bytes(hash_bytes[:4], "big")
        target_length = 12 + (seed % 9)  # 12 ~ 20

        # 整个 32 字节作为字符种子
        value = int.from_bytes(hash_bytes, "big")
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        result = []
        for _ in range(target_length):
            result.append(chars[value % 52])
            value //= 52
            if value == 0:
                value += 1

        # 确保首字母大写
        result[0] = result[0].upper()
        return "".join(result)

    # ── JSON 辅助 ─────────────────────────────────────────────

    @staticmethod
    def _deep_remove_key(obj, key: str):
        """递归删除 obj 中所有 key 属性"""
        if isinstance(obj, dict):
            obj.pop(key, None)
            for v in obj.values():
                CleanSwaggerScript._deep_remove_key(v, key)
        elif isinstance(obj, list):
            for item in obj:
                CleanSwaggerScript._deep_remove_key(item, key)

    @staticmethod
    def _deep_update_refs(obj, ref_mapping: dict[str, str]):
        """递归更新 $ref 引用为混淆后的名称"""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "$ref" and isinstance(v, str):
                    for old_name, new_name in ref_mapping.items():
                        old_ref = f"#/definitions/{old_name}"
                        if v == old_ref:
                            obj[k] = f"#/definitions/{new_name}"
                            break
                elif k == "originalRef" and isinstance(v, str):
                    for old_name, new_name in ref_mapping.items():
                        if v.endswith(f"«{old_name}»"):
                            obj[k] = v.replace(f"«{old_name}»", f"«{new_name}»")
                            break
                else:
                    CleanSwaggerScript._deep_update_refs(v, ref_mapping)
        elif isinstance(obj, list):
            for item in obj:
                CleanSwaggerScript._deep_update_refs(item, ref_mapping)

    # ── 清洗流程 ──────────────────────────────────────────────

    def clean_swagger(self, input_file: str, output_file: str) -> bool:
        """主流程：读取 swagger JSON → 清洗 → 混淆 → 写入 output_file。
        返回 False 表示发现新模型需要用户确认。"""
        with open(input_file, encoding="utf-8") as f:
            swagger = json.load(f)

        swagger = deepcopy(swagger)

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
                            # 收集 header 参数信息
                            hname = param.get("name", "")
                            desc = param.get("description", "")
                            # 提取原始名称: "acqChannel :xxx: obfuscated: 描述"
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
                        # 修复无效 query 参数类型
                        if param.get("in") == "query" and param.get("type", "string") not in VALID_TYPES:
                            old_type = param.get("type", "")
                            param["type"] = "string"
                            desc = param.get("description", "")
                            param["description"] = f"{desc} (原类型: {old_type})" if desc else f"原类型: {old_type}"
                        new_params.append(param)
                    operation["parameters"] = new_params

        # 识别公共 header：出现次数 >= 总接口数 90% 的视为公共 header
        self.common_headers = sorted(
            [h for h in header_counts.values() if h["count"] >= total_ops * 0.9],
            key=lambda h: (not h["required"], h["name"])
        )

        # 步骤 1.1：处理 tags + 混淆 operationId
        swagger_tags = {t["name"]: t.get("description", "") for t in swagger.get("tags", [])}
        for path, methods in swagger.get("paths", {}).items():
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue

                if self.split_by_tag:
                    # 保留原始 tag，但混淆 tag 名
                    original_tags = operation.get("tags", ["Default"])
                    obfuscated_tags = []
                    for t in original_tags:
                        obf_name = self._generate_field_name(t)
                        if t not in self.tag_info:
                            self.tag_info[t] = {
                                "obfuscated": obf_name,
                                "description": swagger_tags.get(t, ""),
                            }
                        obfuscated_tags.append(obf_name)
                    operation["tags"] = obfuscated_tags
                else:
                    operation["tags"] = [self.api_name]

                if self.obfuscate_operation_id and "operationId" in operation:
                    new_id = self._generate_field_name(operation["operationId"])
                    new_id = new_id[0].lower() + new_id[1:] if new_id else new_id
                    operation["operationId"] = new_id

        # 步骤 2：剥离响应包装器（code/msg/data）— 必须在移除 originalRef 之前，因为需要 originalRef 作为 fallback
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

        # 替换 responses 中的引用（支持 $ref 直接在 response 或嵌套在 schema 中）
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
                            # 移除旧引用
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

        # 移除包装器模型定义
        for wname in wrapper_models:
            definitions.pop(wname, None)

        # 步骤 3：移除 originalRef（包装器剥离完成后不再需要）
        self._deep_remove_key(swagger, "originalRef")

        # 步骤 4：过滤非标准 HTTP 代码
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

        # 步骤 5：混淆定义名称
        ref_mapping: dict[str, str] = {}
        for def_name in list(definitions.keys()):
            if def_name in wrapper_models:
                continue
            if def_name in self.model_name_map:
                ref_mapping[def_name] = self.model_name_map[def_name]
            else:
                new_name = self._generate_field_name(def_name)
                ref_mapping[def_name] = new_name
                self._new_mappings[def_name] = new_name

        # 重命名 definitions
        new_definitions = {}
        for old_name, schema in definitions.items():
            new_name = ref_mapping.get(old_name, old_name)
            new_definitions[new_name] = schema
        swagger["definitions"] = new_definitions

        # 步骤 6：更新所有引用
        self._deep_update_refs(swagger, ref_mapping)

        # 步骤 7：导出映射 + 公共 headers
        if self.export_model_mapping_file:
            try:
                merged = dict(self.model_name_map)
                merged.update(self._new_mappings)
                export_dir = os.path.dirname(self.export_model_mapping_file)
                if export_dir:
                    os.makedirs(export_dir, exist_ok=True)
                with open(self.export_model_mapping_file, "w", encoding="utf-8") as f:
                    json.dump(merged, f, ensure_ascii=False, indent=2)
                if self._new_mappings:
                    print(f"Exported {len(self._new_mappings)} new model name mappings to "
                          f"{self.export_model_mapping_file}")
            except Exception as e:
                print(f"Error writing model name map: {e}")

        if self.export_common_headers_file and self.common_headers:
            try:
                export_dir = os.path.dirname(self.export_common_headers_file)
                if export_dir:
                    os.makedirs(export_dir, exist_ok=True)
                with open(self.export_common_headers_file, "w", encoding="utf-8") as f:
                    json.dump(self.common_headers, f, ensure_ascii=False, indent=2)
                print(f"Exported {len(self.common_headers)} common headers to "
                      f"{self.export_common_headers_file}")
            except Exception as e:
                print(f"Error writing common headers: {e}")

        # 步骤 8：检查新增模型
        if self.model_name_map and self._new_mappings:
            print("\n⚠ New model names detected (need confirmation):")
            for old, new in sorted(self._new_mappings.items()):
                print(f"  {old} → {new}")
            print("\nPlease review the new mappings and re-run with --modelNameMap "
                  "pointing to the exported mapping file.")
            return False

        # 步骤 9：写入输出
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(swagger, f, ensure_ascii=False, indent=2)
            print(f"Cleaned swagger written to {output_file}")
        except Exception as e:
            print(f"Error writing cleaned swagger: {e}")

        return True
