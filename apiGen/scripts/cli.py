"""CLI 参数解析 — 与 api_gen 保持一致的命令行接口"""

from __future__ import annotations

import argparse
import os
import sys


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="api_gen_py — 将 Swagger API 文档转换为 Kotlin 代码（suspend + Retrofit2 + kotlinx.serialization）"
    )

    parser.add_argument("--outputDir", default="app",
                        help="输出目录 (默认: app)")
    parser.add_argument("--package", dest="package_name", default=None,
                        help="生成代码的根包名 (必填，如 com.myapp.api)")
    parser.add_argument("--modelPackage", dest="model_package", default=None,
                        help="模型包名 (默认: {package}.model)")
    parser.add_argument("--apiPackage", dest="api_package", default=None,
                        help="API 包名 (默认: {package}.api)")
    parser.add_argument("--sourceFolder", dest="source_folder", default=None,
                        help="源码子目录 (默认: src/main/kotlin)")
    parser.add_argument("--swaggerApiUrl", default="",
                        help="Swagger JSON URL 或本地文件路径 (必填)")
    parser.add_argument("--baseResponseName", dest="base_response_name",
                        default="BaseResponse",
                        help="响应基类名称 (默认: BaseResponse)")
    parser.add_argument("--apiName", default="ApiService",
                        help="接口名称，--splitByTag false 时生效 (默认: ApiService)")
    parser.add_argument("--obfuscateOperationId", dest="obfuscate_operation_id",
                        default="true",
                        help="是否混淆 operationId (默认: true)")
    parser.add_argument("--salt", default=None,
                        help="混淆盐值 (必填)")
    parser.add_argument("--apiGenDir", dest="api_gen_dir", default=None,
                        help="apiGen 工作目录 (默认: <outputDir>/api_gen)")
    parser.add_argument("--disableModelMapping", dest="disable_model_mapping",
                        default="false",
                        help="禁用模型名称映射 (默认: false)")
    parser.add_argument("--modelNameMap", dest="model_name_map", default=None,
                        help="模型名称映射 JSON 文件路径")
    parser.add_argument("--exportModelNameMap", dest="export_model_name_map",
                        default=None,
                        help="导出模型名称映射到 JSON 文件")
    parser.add_argument("--exportMappingOnly", dest="export_mapping_only",
                        default="false",
                        help="仅导出映射文件，不生成代码 (默认: false)")
    parser.add_argument("--splitByTag", dest="split_by_tag",
                        default="false",
                        help="按 Swagger tag 拆分多个接口文件 (默认: false)")

    parsed = parser.parse_args(args)

    # 必填参数验证（在默认值推导之前）
    if not parsed.package_name:
        print("Error: --package is required (e.g. --package com.myapp.api)")
        sys.exit(1)

    # 布尔值转换
    parsed.obfuscate_operation_id = parsed.obfuscate_operation_id.lower() == "true"
    parsed.disable_model_mapping = parsed.disable_model_mapping.lower() == "true"
    parsed.export_mapping_only = parsed.export_mapping_only.lower() == "true"
    parsed.split_by_tag = parsed.split_by_tag.lower() == "true"

    # 默认值推导
    if parsed.model_package is None:
        parsed.model_package = f"{parsed.package_name}.model"
    if parsed.api_package is None:
        parsed.api_package = f"{parsed.package_name}.api"
    if parsed.source_folder is None:
        parsed.source_folder = "src/main/kotlin"

    # apiGenDir 默认值
    if parsed.api_gen_dir is None:
        if parsed.outputDir.strip():
            parsed.api_gen_dir = os.path.join(parsed.outputDir, "api_gen")
        else:
            parsed.api_gen_dir = "api_gen"

    # exportModelNameMap 默认值
    if parsed.export_model_name_map is None and not parsed.disable_model_mapping:
        parsed.export_model_name_map = os.path.join(parsed.api_gen_dir, "model_name_mapping.json")

    # 验证
    if not parsed.salt.strip():
        print("Error: salt is required")
        sys.exit(1)

    if not parsed.swaggerApiUrl.strip():
        print("Error: swaggerApiUrl is blank")
        sys.exit(1)

    return parsed
