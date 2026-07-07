"""swagger_generate MCP tool — 从 Swagger JSON 生成可读 Kotlin 代码（不混淆，增量合并）。

导入自原 swagger-generate-interface/scripts/ 的核心模块。
"""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout

# 将原 swagger-generate-interface scripts 目录加入 path
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "swagger-generate-interface", "scripts"
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from cleaner import SwaggerCleaner
from generator import generate as _generate_kotlin

from ..common.loader import load_swagger


def run(
    swagger_url: str,
    package: str,
    output_dir: str = "app",
    split_by_tag: bool = False,
    model_names: str | None = None,
) -> dict:
    """执行代码生成，返回结构化结果。

    Args:
        swagger_url: Swagger JSON URL 或本地文件路径
        package: Kotlin 根包名
        output_dir: 输出目录
        split_by_tag: 按 tag 拆分接口
        model_names: 中文模型名→英文映射，格式 "原名:EnName,..."

    Returns:
        {
            "ok": bool,
            "output": str,        # 完整标准输出
            "files": [str],       # 生成/更新的文件列表
            "warnings": [str],    # 哈希名警告
            "errors": [str],
        }
    """
    result: dict = {
        "ok": True,
        "output": "",
        "files": [],
        "warnings": [],
        "errors": [],
    }

    # 1. 加载 Swagger JSON
    try:
        swagger = load_swagger(swagger_url)
    except Exception as e:
        result["ok"] = False
        result["errors"].append(f"加载 Swagger 失败: {e}")
        return result

    # 2. 解析 model_names
    model_names_dict: dict[str, str] = {}
    if model_names:
        for pair in model_names.split(","):
            pair = pair.strip()
            if ":" in pair:
                k, v = pair.split(":", 1)
                model_names_dict[k.strip()] = v.strip()

    # 3. 清洗 Swagger JSON
    cleaner = SwaggerCleaner(split_by_tag=split_by_tag)
    cleaned = cleaner.clean(swagger)
    if cleaned is None:
        result["ok"] = False
        result["errors"].append("清洗 Swagger JSON 失败")
        return result

    # 4. 生成 Kotlin 代码（捕获标准输出）
    model_package = f"{package}.model"
    api_package = f"{package}.api"

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            _generate_kotlin(
                swagger=cleaned,
                output_dir=output_dir,
                package_name=package,
                model_package=model_package,
                api_package=api_package,
                base_response_name="BaseResponse",
                common_headers=cleaner.common_headers,
                split_by_tag=split_by_tag,
                tag_info=cleaner.tag_info if split_by_tag else None,
                model_names=model_names_dict if model_names_dict else None,
            )
        output_text = buf.getvalue()
        result["output"] = output_text

        # 5. 解析输出提取文件变更和警告
        for line in output_text.splitlines():
            line = line.strip()
            if not line:
                continue
            # 提取文件变更
            if line.startswith("[generated]") or line.startswith("[updated]") or line.startswith("[skipped]"):
                result["files"].append(line)
            # 提取哈希名警告
            elif line.startswith("⚠"):
                result["warnings"].append(line)

        # 检查非 ASCII 模型名
        definitions = swagger.get("definitions", {})
        non_ascii = [n for n in definitions if not n.isascii() or any(c in n for c in " \t")]
        uncovered = [n for n in non_ascii if n not in model_names_dict]
        if uncovered:
            result["warnings"].append(
                f"检测到 {len(uncovered)} 个非 ASCII 模型名未提供映射: {', '.join(uncovered)}"
            )

    except Exception as e:
        import traceback
        result["ok"] = False
        result["errors"].append(f"代码生成失败: {e}\n{traceback.format_exc()}")

    return result
