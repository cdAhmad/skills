"""Swagger JSON 下载、MD5 缓存、变更检测"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from datetime import datetime


class SwaggerUpdater:
    def __init__(self, swagger_api_url: str, api_gen_dir: str):
        self.swagger_api_url = swagger_api_url
        self.api_gen_dir = api_gen_dir
        self.log_dir = os.path.join(api_gen_dir, "logs")
        self.history_dir = os.path.join(api_gen_dir, "history")
        self.downloaded_file = os.path.join(self.log_dir, "default_OpenAPI.json")
        self.md5_file = os.path.join(self.log_dir, "swagger_md5.txt")
        self.old_file = os.path.join(self.log_dir, "swagger_old.json")
        self.log_file = os.path.join(api_gen_dir, "swagger_update.log")

        os.makedirs(self.api_gen_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)

    def download_swagger_json(self) -> bool:
        print(f"Downloading swagger json file from {self.swagger_api_url}...")
        try:
            req = urllib.request.Request(self.swagger_api_url, headers={
                "User-Agent": "api_gen_py/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8").strip()
            if not text:
                raise Exception("Empty response body")
            with open(self.downloaded_file, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Download completed, saved to {self.downloaded_file}")
            return True
        except Exception as e:
            print(f"Download failed: {e}")
            return False

    @staticmethod
    def calculate_md5(file_path: str) -> str:
        md = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md.update(chunk)
        return md.hexdigest()

    @staticmethod
    def _param_key(p: dict) -> str:
        return f"{p.get('in','')}:{p.get('name','')}"

    @staticmethod
    def _param_desc(p: dict) -> str:
        """提取字段的人类可读描述"""
        desc = p.get("description", "")
        if desc and ":" in desc:
            # Swagger 混淆格式: "originalName :hash: obfuscated: 中文描述"
            parts = desc.split(":", 1)
            first = parts[0].strip()
            cn = desc.rsplit(":", 1)[-1].strip() if desc.count(":") >= 3 else ""
            if cn:
                return f"{first} ({cn})"
            return first
        # 只用字段名兜底
        name = p.get("name", "")
        if name:
            return name
        return desc or "(unknown)"

    def _compare_params(self, old_params: list, new_params: list,
                        old_defs: dict, new_defs: dict) -> list[str]:
        """对比参数列表，返回变更详情列表"""
        details = []
        old_map = {self._param_key(p): p for p in old_params}
        new_map = {self._param_key(p): p for p in new_params}

        for key, np in new_map.items():
            if key not in old_map:
                desc = self._param_desc(np)
                pin = np.get("in", "?")
                details.append(f"    + 新增 {pin} 参数: {desc}")
            else:
                op = old_map[key]
                # 检查类型变更（仅当两边类型来源一致时才比较）
                ot_primitive = op.get("type", "")
                nt_primitive = np.get("type", "")
                ot_ref = op.get("schema", {}).get("$ref", "")
                nt_ref = np.get("schema", {}).get("$ref", "")
                if ot_primitive and nt_primitive:
                    if ot_primitive != nt_primitive:
                        details.append(f"    * 类型变更 {self._param_desc(np)}: {ot_primitive} → {nt_primitive}")
                elif ot_ref and nt_ref:
                    if ot_ref != nt_ref:
                        details.append(f"    * 类型变更 {self._param_desc(np)}: {ot_ref} → {nt_ref}")
                elif (ot_primitive or ot_ref) and (nt_primitive or nt_ref):
                    # 一侧是原始类型另一侧是引用，这算真正的变更
                    ot_desc = ot_primitive or ot_ref
                    nt_desc = nt_primitive or nt_ref
                    if ot_desc != nt_desc:
                        details.append(f"    * 类型变更 {self._param_desc(np)}: {ot_desc} → {nt_desc}")
                # 检查 body 参数的 schema 字段变更
                if op.get("in") == "body" and np.get("in") == "body":
                    old_body_schema = op.get("schema", {})
                    new_body_schema = np.get("schema", {})
                    body_field_details = self._compare_schema_fields(
                        old_body_schema, new_body_schema, old_defs, new_defs)
                    details.extend(body_field_details)
                # 检查 required 变更
                if op.get("required") != np.get("required"):
                    details.append(f"    * 必填变更 {self._param_desc(np)}: {op.get('required')} → {np.get('required')}")

        for key, op in old_map.items():
            if key not in new_map:
                desc = self._param_desc(op)
                details.append(f"    - 删除参数: {desc}")

        return details

    @staticmethod
    def _resolve_ref(schema: dict, definitions: dict) -> dict | None:
        """解析 $ref 或 originalRef 指向的实际 definition"""
        ref = schema.get("$ref", "")
        if ref.startswith("#/definitions/"):
            name = ref[len("#/definitions/"):]
            return definitions.get(name)
        orig = schema.get("originalRef", "")
        if orig and orig in definitions:
            return definitions[orig]
        return None

    def _deep_resolve(self, schema: dict, definitions: dict) -> dict:
        """递归解析所有 $ref/originalRef，返回完全展开的 schema 副本"""
        # 先解析顶层引用
        resolved = self._resolve_ref(schema, definitions)
        if resolved:
            schema = resolved

        result = dict(schema)
        props = result.get("properties", {})
        if props:
            new_props = {}
            for pname, pschema in props.items():
                new_props[pname] = self._deep_resolve(pschema, definitions)
            result["properties"] = new_props
        return result

    def _compare_schema_fields(self, old_schema: dict, new_schema: dict,
                               old_defs: dict, new_defs: dict, prefix: str = "") -> list[str]:
        """递归对比 schema 字段变更"""
        details = []

        # 解析 $ref
        old_def = self._resolve_ref(old_schema, old_defs)
        new_def = self._resolve_ref(new_schema, new_defs)

        if old_def and new_def:
            # 对比 definition 的 properties
            return self._compare_schema_fields(old_def, new_def, old_defs, new_defs, prefix)

        old_props = old_schema.get("properties", {})
        new_props = new_schema.get("properties", {})

        for pname, pschema in new_props.items():
            pschema_with_name = dict(pschema, name=pname) if isinstance(pschema, dict) else {"name": pname}
            if pname not in old_props:
                desc = self._param_desc(pschema_with_name)
                details.append(f"{prefix}    + 新增返回字段: {desc}")
            else:
                old_type = json.dumps(old_props[pname], sort_keys=True)
                new_type = json.dumps(pschema, sort_keys=True)
                if old_type != new_type:
                    desc = self._param_desc(pschema_with_name)
                    # 如果字段本身是对象，递归比较子字段
                    old_child = old_props.get(pname, {})
                    new_child = pschema
                    if isinstance(old_child, dict) and isinstance(new_child, dict):
                        child_details = self._compare_schema_fields(
                            old_child, new_child, old_defs, new_defs,
                            f"{prefix}    [{desc}]")
                        if child_details:
                            details.extend(child_details)
                        else:
                            details.append(f"{prefix}    * 返回字段变更: {desc}")
                    else:
                        details.append(f"{prefix}    * 返回字段变更: {desc}")

        for pname, pschema in old_props.items():
            if pname not in new_props:
                pschema_with_name = dict(pschema, name=pname) if isinstance(pschema, dict) else {"name": pname}
                desc = self._param_desc(pschema_with_name)
                details.append(f"{prefix}    - 删除返回字段: {desc}")

        return details

    def compare_swagger(self, old_file: str, new_file: str) -> dict:
        """对比两个 swagger JSON 的 paths/参数/响应差异，返回详细变更报告"""
        with open(old_file, encoding="utf-8") as f:
            old_swagger = json.load(f)
        with open(new_file, encoding="utf-8") as f:
            new_swagger = json.load(f)

        old_paths = old_swagger.get("paths", {})
        new_paths = new_swagger.get("paths", {})
        old_defs = old_swagger.get("definitions", {})
        new_defs = new_swagger.get("definitions", {})

        changes = {"added_paths": [], "removed_paths": [], "modified_paths": []}

        # 新增接口
        for path, value in new_paths.items():
            if path not in old_paths:
                for method in value:
                    if isinstance(value[method], dict):
                        summary = value[method].get("summary", "无描述")
                        changes["added_paths"].append(f"{method.upper()} {path} - {summary}")

        # 删除接口
        for path, value in old_paths.items():
            if path not in new_paths:
                for method in value:
                    if isinstance(value[method], dict):
                        summary = value[method].get("summary", "无描述")
                        changes["removed_paths"].append(f"{method.upper()} {path} - {summary}")

        # 修改接口 → 详细对比
        for path, value in old_paths.items():
            if path not in new_paths:
                continue
            for method in value:
                if method not in new_paths[path]:
                    continue
                old_op = value[method]
                new_op = new_paths[path][method]
                if not isinstance(old_op, dict) or not isinstance(new_op, dict):
                    continue

                details = []

                # 对比参数
                old_params = old_op.get("parameters", [])
                new_params = new_op.get("parameters", [])
                if old_params or new_params:
                    param_changes = self._compare_params(old_params, new_params, old_defs, new_defs)
                    details.extend(param_changes)

                # 对比响应码
                old_resp = old_op.get("responses", {})
                new_resp = new_op.get("responses", {})
                for code in new_resp:
                    if code not in old_resp:
                        desc = new_resp[code].get("description", "") if isinstance(new_resp[code], dict) else ""
                        details.append(f"    + 新增响应码: {code} {desc}".strip())
                for code in old_resp:
                    if code not in new_resp:
                        desc = old_resp[code].get("description", "") if isinstance(old_resp[code], dict) else ""
                        details.append(f"    - 删除响应码: {code} {desc}".strip())
                    elif isinstance(old_resp[code], dict) and isinstance(new_resp[code], dict):
                        old_schema = old_resp[code].get("schema", {})
                        new_schema = new_resp[code].get("schema", {})
                        old_resolved = self._deep_resolve(old_schema, old_defs)
                        new_resolved = self._deep_resolve(new_schema, new_defs)
                        old_s = json.dumps(old_resolved, sort_keys=True)
                        new_s = json.dumps(new_resolved, sort_keys=True)
                        if old_s != new_s:
                            field_details = self._compare_schema_fields(
                                old_resolved, new_resolved, old_defs, new_defs, "")
                            if field_details:
                                details.append(f"    * 响应 {code} 返回字段变更:")
                                details.extend(field_details)
                            else:
                                details.append(f"    * 响应 {code} schema 变更")

                # 对比 description/summary 变更
                if old_op.get("summary") != new_op.get("summary"):
                    details.append(f"    * 接口描述变更: {old_op.get('summary','')} → {new_op.get('summary','')}")

                if details:
                    summary = new_op.get("summary", "无描述")
                    header = f"{method.upper()} {path} - {summary}"
                    changes["modified_paths"].append(header)
                    changes["modified_paths"].extend(details)

        return changes

    def _load_local_file(self) -> bool:
        """将本地 swagger JSON 文件复制到 downloaded_file 位置"""
        print(f"Loading swagger json from local file: {self.swagger_api_url}")
        try:
            shutil.copy(self.swagger_api_url, self.downloaded_file)
            print(f"Loaded, saved to {self.downloaded_file}")
            return True
        except Exception as e:
            print(f"Failed to load local file: {e}")
            return False

    def run(self) -> bool:
        # 下载 / 加载本地文件
        if os.path.isfile(self.swagger_api_url):
            if not self._load_local_file():
                return False
        elif self.swagger_api_url:
            if not self.download_swagger_json():
                return False
        else:
            if not os.path.isfile(self.downloaded_file):
                print(f"Error: swaggerapiurl is empty and no cached file found at {self.downloaded_file}")
                return False
            print(f"swaggerapiurl is empty, using cached file: {self.downloaded_file}")

        # 计算 MD5
        try:
            current_md5 = self.calculate_md5(self.downloaded_file)
        except FileNotFoundError:
            print(f"Error: swagger JSON file not found: {self.downloaded_file}")
            return False
        print(f"Current swagger json MD5 value: {current_md5}")

        # 读取之前的 MD5
        previous_md5 = None
        if os.path.exists(self.md5_file):
            with open(self.md5_file, encoding="utf-8") as f:
                previous_md5 = f.read().strip()
            print(f"Previous swagger json MD5 value: {previous_md5}")

        # MD5 相同则跳过
        if previous_md5 == current_md5:
            print("swagger json file has not changed, skipping subsequent execution")
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
                        f"swagger json file has not changed, MD5: {current_md5}\n")
            return False

        if previous_md5 is None:
            # 首次运行
            print("First run, printing all API information...")
            with open(self.downloaded_file, encoding="utf-8") as f:
                swagger = json.load(f)
            paths = swagger.get("paths", {})
            all_paths = []
            for path, value in paths.items():
                for method in value:
                    summary = value[method].get("summary", "No description")
                    all_paths.append(f"{method.upper()} {path} - {summary}")

            print("All APIs:")
            for p in all_paths:
                print(f"  - {p}")

            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] First run, all APIs:\n")
                for p in all_paths:
                    f.write(f"  - {p}\n")

            # 保存基线
            shutil.copy(self.downloaded_file, self.old_file)
        else:
            # 检测变更
            try:
                changes = self.compare_swagger(self.old_file, self.downloaded_file)
            except Exception as e:
                print(f"Error comparing differences: {e}")
                changes = {"added_paths": [], "removed_paths": [], "modified_paths": []}

            # 保存历史快照
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy(self.downloaded_file,
                       os.path.join(self.history_dir, f"swagger_{timestamp}.json"))
            shutil.copy(self.downloaded_file, self.old_file)

            ts = datetime.now()
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
            ts_file = ts.strftime("%Y%m%d_%H%M%S")

            # 1) 主日志追加
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts_str}] swagger json file updated, MD5: {current_md5}\n")
                for key, label in [("added_paths", "Added APIs"),
                                   ("removed_paths", "Removed APIs"),
                                   ("modified_paths", "Modified APIs")]:
                    if changes[key]:
                        f.write(f"{label}:\n")
                        for p in changes[key]:
                            f.write(f"  {p}\n")

            # 2) 独立 changelog 文件
            changelog_file = os.path.join(self.log_dir, f"changelog_{ts_file}.md")
            with open(changelog_file, "w", encoding="utf-8") as f:
                f.write(f"# Swagger API 变更报告\n\n")
                f.write(f"**时间**: {ts_str}\n\n")
                f.write(f"**MD5**: `{current_md5}`\n\n")
                f.write(f"---\n\n")
                for key, label, emoji in [
                    ("added_paths", "新增接口", "+"),
                    ("removed_paths", "删除接口", "-"),
                    ("modified_paths", "修改接口", "*"),
                ]:
                    if changes[key]:
                        f.write(f"## {label}\n\n")
                        for p in changes[key]:
                            icon = emoji if not p.startswith(" ") else " "
                            f.write(f"{icon} {p}\n")
                        f.write("\n")
            print(f"Changelog written to {changelog_file}")

            # 3) 打印变更到控制台
            print("swagger json file has been updated, continuing with subsequent steps")
            for key, label in [("added_paths", "Added APIs"),
                               ("removed_paths", "Removed APIs"),
                               ("modified_paths", "Modified APIs")]:
                if changes[key]:
                    print(f"{label}:")
                    for p in changes[key]:
                        print(f"  {p}")

        # 更新 MD5
        with open(self.md5_file, "w", encoding="utf-8") as f:
            f.write(current_md5)

        return True
