#!/usr/bin/env python3
"""api_gen_py — Swagger API 文档转 Kotlin 代码（suspend + Retrofit2 + kotlinx.serialization）"""

import json
import os
import sys

from cli import parse_args
from swagger_updater import SwaggerUpdater
from clean_swagger import CleanSwaggerScript
from generator import generate


def main():
    args = parse_args()

    salt = f"swagger-kotlin-codegen-salt-{args.salt}"  # 保持相同前缀以兼容

    print("Configuration:")
    print(f"  outputDir: {args.outputDir}")
    print(f"  package: {args.package_name}")
    print(f"  modelPackage: {args.model_package}")
    print(f"  apiPackage: {args.api_package}")
    print(f"  swaggerApiUrl: {args.swaggerApiUrl}")
    print(f"  baseResponseName: {args.base_response_name}")
    print(f"  salt: {salt}")
    print(f"  apiName: {args.apiName}")
    print(f"  obfuscateOperationId: {args.obfuscate_operation_id}")
    print(f"  apiGenDir: {args.api_gen_dir}")
    print(f"  disableModelMapping: {args.disable_model_mapping}")
    print(f"  modelNameMap: {args.model_name_map or '<none>'}")
    print(f"  exportModelNameMap: {args.export_model_name_map or '<disabled>'}")
    print(f"  splitByTag: {args.split_by_tag}")
    print(f"  modelPrefix: {args.model_prefix!r}")
    print()

    # 0. 准备工作
    os.makedirs(args.api_gen_dir, exist_ok=True)
    now = __import__('datetime').datetime.now()
    saved_args = sys.argv[1:]

    # 将 --key value 配对到同一行
    formatted_args = []
    i = 0
    while i < len(saved_args):
        a = saved_args[i]
        if a.startswith("--") and i + 1 < len(saved_args) and not saved_args[i + 1].startswith("--"):
            formatted_args.append(f"{a} {saved_args[i + 1]}")
            i += 2
        else:
            formatted_args.append(a)
            i += 1

    # 命令行片段（相对路径，供 generate.sh 和 history 复用）
    cmd_line = f"python3 scripts/main.py"
    if formatted_args:
        cmd_line += " \\\n  " + " \\\n  ".join(formatted_args)

    history_file = os.path.join(args.api_gen_dir, "command_history.log")
    log_file = os.path.join(args.api_gen_dir, "swagger_update.log")

    # 记录 salt 到更新日志
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{now:%Y-%m-%d %H:%M:%S}] salt: {args.salt}\n")

    # 1. 下载 Swagger JSON
    updater = SwaggerUpdater(args.swaggerApiUrl, args.api_gen_dir)
    if not updater.run():
        # MD5 未变更，跳过生成
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(f"[{now:%Y-%m-%d %H:%M:%S}] 跳过: Swagger 未变更\n")
            f.write(f"  命令: {cmd_line.replace(chr(10), ' ')}\n\n")
        return

    # 1.1 提取 host + info.title 作为站点标识
    input_file = os.path.join(args.api_gen_dir, "logs", "default_OpenAPI.json")
    try:
        with open(input_file, encoding="utf-8") as f:
            swagger_json = json.load(f)
        host = swagger_json.get("host", "") or args.swaggerApiUrl
        title = swagger_json.get("info", {}).get("title", "")
    except Exception:
        host = args.swaggerApiUrl
        title = ""
    print(f"  host: {host}")

    # 1.2 写入命令历史（使用 host 区分站点）
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(f"[{now:%Y-%m-%d %H:%M:%S}] host: {host}")
        if title:
            f.write(f"  ({title})")
        f.write(f"  Salt: {args.salt}\n")
        f.write(f"  {cmd_line.replace(chr(10)+'  ', ' ').replace(chr(10), ' ')}\n\n")

    # 2. 加载 model name mapping
    model_name_map: dict[str, str] = {}
    if not args.disable_model_mapping:
        map_file = args.model_name_map
        if not map_file:
            default_map = os.path.join(args.api_gen_dir, "model_name_mapping.json")
            if os.path.exists(default_map):
                map_file = default_map

        if map_file and os.path.exists(map_file):
            try:
                with open(map_file, encoding="utf-8") as f:
                    model_name_map = json.load(f)
                print(f"Loaded {len(model_name_map)} model name mappings from {map_file}")
            except Exception as e:
                print(f"Warning: failed to parse modelNameMap: {e}")

    # 3. 清洗 Swagger JSON
    print("\nRunning clean_swagger_script...")
    common_headers_file = os.path.join(args.api_gen_dir, "logs", "common_headers.json")
    clean = CleanSwaggerScript(
        salt=salt,
        api_name=args.apiName,
        obfuscate_operation_id=args.obfuscate_operation_id,
        model_name_map=model_name_map,
        export_model_mapping_file=args.export_model_name_map,
        export_common_headers_file=common_headers_file,
        split_by_tag=args.split_by_tag,
    )

    output_file = os.path.join(args.api_gen_dir, "logs", "temp.json")

    try:
        ok = clean.clean_swagger(input_file, output_file)
        if not ok:
            print("clean_swagger_script interrupted: new model mappings need confirmation")
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(f"  -> 中断: 新模型映射需确认\n\n")
            return
        print("clean_swagger_script executed successfully")
    except Exception as e:
        print(f"clean_swagger_script execution failed: {e}")
        return

    # 4. 验证 temp.json
    if not os.path.exists(output_file):
        print("Error: temp.json file was not generated")
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(f"  -> 失败: temp.json 未生成\n\n")
        return

    # 4.1 仅导出映射模式：生成映射文件后停止，不生成 Kotlin 代码
    if args.export_mapping_only:
        map_file = args.export_model_name_map or os.path.join(
            args.api_gen_dir, "model_name_mapping.json")
        print(f"\nMapping exported to: {map_file}")
        print("Please review and modify the mapping file, then re-run without --exportMappingOnly.")
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(f"  -> 仅导出映射\n\n")
        return

    # 5. 生成新 Kotlin 代码
    print("\nGenerating Kotlin code...")
    full_mapping = dict(clean.model_name_map)
    full_mapping.update(clean._new_mappings)
    try:
        generate(
            input_file=output_file,
            output_dir=args.outputDir,
            package_name=args.package_name,
            model_package=args.model_package,
            api_package=args.api_package,
            base_response_name=args.base_response_name,
            common_headers=clean.common_headers,
            model_name_mapping=full_mapping,
            split_by_tag=args.split_by_tag,
            tag_info=clean.tag_info if args.split_by_tag else None,
            source_folder=args.source_folder,
            api_name=args.apiName,
            model_prefix=args.model_prefix,
        )
    except Exception as e:
        print(f"Code generation failed: {e}")
        import traceback
        traceback.print_exc()
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(f"  -> 失败: {e}\n\n")
        return

    # 5.1 写入 generate.sh（仅在实际生成成功后覆盖）
    script_path = os.path.abspath(__file__)
    output_dir_abs = os.path.abspath(args.outputDir)
    cmd_file = os.path.join(args.api_gen_dir, "generate.sh")
    with open(cmd_file, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n")
        f.write(f"# 最后一次成功生成命令 (含 salt，请勿丢失此文件)\n")
        f.write(f"# 生成时间: {now:%Y-%m-%d %H:%M:%S}\n")
        f.write(f"# host:  {host}\n")
        f.write(f"# Salt:  {args.salt}\n")
        f.write("cd \"$(dirname \"$0\")/..\"\n")
        f.write(f"python3 {script_path}")
        if formatted_args:
            f.write(" \\\n")
            for i, a in enumerate(formatted_args):
                # 将相对路径 outputDir 替换为绝对路径，确保从任意目录运行都正确
                if a.startswith("--outputDir ") or a.startswith("--outputDir="):
                    parts = a.split(" ", 1)
                    if len(parts) == 2:
                        a = f"--outputDir {output_dir_abs}"
                    else:
                        a = f"--outputDir={output_dir_abs}"
                suffix = " \\\n" if i < len(formatted_args) - 1 else "\n"
                f.write(f"  {a}{suffix}")
        else:
            f.write("\n")
    os.chmod(cmd_file, 0o755)
    print(f"Command saved to {cmd_file}")

    # 5.2 追加成功状态到命令历史
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(f"  -> 生成成功\n\n")

    print("\nAll operations completed!")


if __name__ == "__main__":
    main()
