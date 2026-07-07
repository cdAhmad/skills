"""CLI 参数解析 — 精简版，6 个参数（2 个必填）"""

from __future__ import annotations

import argparse
import sys


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="swagger-generate-interface — 从 Swagger JSON 生成 Kotlin 接口 + 模型（不混淆命名，支持增量合并）"
    )

    parser.add_argument("--swaggerApiUrl", default="",
                        help="Swagger JSON URL 或本地文件路径（必填）")
    parser.add_argument("--package", dest="package_name", default=None,
                        help="生成代码的根包名（必填，如 com.myapp.api）")
    parser.add_argument("--outputDir", dest="output_dir", default="app",
                        help="输出目录（默认: app）")
    parser.add_argument("--sourceFolder", dest="source_folder", default="src/main/kotlin",
                        help="源码子目录（默认: src/main/kotlin）")
    parser.add_argument("--splitByTag", dest="split_by_tag", default="false",
                        help="按 Swagger tag 拆分多个接口文件（默认: false）")
    parser.add_argument("--baseResponse", dest="base_response_name", default="BaseResponse",
                        help="响应包装类名（默认: BaseResponse）")
    parser.add_argument("--modelNames", dest="model_names", default=None,
                        help="中文模型名→英文类名映射，格式: \"中文1:En1,中文2:En2\"")

    parsed = parser.parse_args(args)

    # 必填参数校验
    if not parsed.package_name:
        print("Error: --package is required (e.g. --package com.myapp.api)")
        sys.exit(1)
    if not parsed.swaggerApiUrl.strip():
        print("Error: --swaggerApiUrl is required")
        sys.exit(1)

    # 布尔值转换
    parsed.split_by_tag = parsed.split_by_tag.lower() == "true"

    # 自动推导
    parsed.model_package = f"{parsed.package_name}.model"
    parsed.api_package = f"{parsed.package_name}.api"

    # 解析 --modelNames "中文1:En1,中文2:En2" → dict
    if parsed.model_names:
        parsed.model_names_dict: dict[str, str] = {}
        for pair in parsed.model_names.split(","):
            pair = pair.strip()
            if ":" in pair:
                k, v = pair.split(":", 1)
                parsed.model_names_dict[k.strip()] = v.strip()
            elif pair:
                print(f"Warning: invalid --modelNames entry '{pair}', expected format '原始名:EnglishName'")
    else:
        parsed.model_names_dict = {}

    return parsed
