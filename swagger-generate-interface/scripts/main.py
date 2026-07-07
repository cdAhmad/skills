#!/usr/bin/env python3
"""swagger-generate-interface — 从 Swagger JSON 生成 Kotlin 接口 + 模型（不混淆，增量合并）"""

import sys

from cli import parse_args
from swagger_loader import SwaggerLoader
from cleaner import SwaggerCleaner
from generator import generate


def main():
    args = parse_args()

    print("Configuration:")
    print(f"  swaggerApiUrl: {args.swaggerApiUrl}")
    print(f"  package: {args.package_name}")
    print(f"  outputDir: {args.output_dir}")
    print(f"  sourceFolder: {args.source_folder}")
    print(f"  splitByTag: {args.split_by_tag}")
    print(f"  baseResponse: {args.base_response_name}")
    if args.model_names_dict:
        print(f"  modelNames: {args.model_names_dict}")
    print()

    # 1. 加载 Swagger JSON
    print("Loading Swagger JSON...")
    swagger = SwaggerLoader.load(args.swaggerApiUrl)
    if swagger is None:
        print("Error: Failed to load Swagger JSON")
        sys.exit(1)
    print("Swagger JSON loaded successfully")

    # 检测非 ASCII definition 名（提醒 Agent 翻译）
    definitions = swagger.get("definitions", {})
    non_ascii = [n for n in definitions if not n.isascii() or any(c in n for c in " \t")]
    uncovered = [n for n in non_ascii if n not in (args.model_names_dict or {})]
    if non_ascii and uncovered:
        print(f"\n⚠ 检测到 {len(non_ascii)} 个非 ASCII 模型名，其中 {len(uncovered)} 个未提供映射:")
        for n in non_ascii:
            status = "✓" if n in (args.model_names_dict or {}) else "⚠ 将使用哈希名"
            print(f"  {status} {n}")
        if uncovered:
            print("Agent 请翻译未映射的名称，通过 --modelNames \"原名:英文名,...\" 传入\n")

    # 2. 清洗
    print("\nCleaning Swagger JSON...")
    cleaner = SwaggerCleaner(split_by_tag=args.split_by_tag)
    cleaned = cleaner.clean(swagger)
    if cleaned is None:
        print("Error: Failed to clean Swagger JSON")
        sys.exit(1)
    print("Cleaning completed")

    # 3. 生成 Kotlin 代码
    print("\nGenerating Kotlin code...")
    try:
        generate(
            swagger=cleaned,
            output_dir=args.output_dir,
            package_name=args.package_name,
            model_package=args.model_package,
            api_package=args.api_package,
            base_response_name=args.base_response_name,
            common_headers=cleaner.common_headers,
            split_by_tag=args.split_by_tag,
            tag_info=cleaner.tag_info if args.split_by_tag else None,
            source_folder=args.source_folder,
            model_names=args.model_names_dict if args.model_names_dict else None,
        )
    except Exception as e:
        print(f"Code generation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\nAll operations completed!")


if __name__ == "__main__":
    main()
