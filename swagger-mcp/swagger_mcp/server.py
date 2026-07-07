"""swagger-mcp — Swagger 辅助工具 MCP Server。

提供:
- 2 个 tool:
  - swagger_generate: Swagger → Kotlin 代码生成（可读命名，增量合并）
  - swagger_annotate: 为 Kotlin Bean 字段补充 KDoc 注释
- 4 个 resource (swaggerlog://*):
  - interceptor: SwaggerLoggingInterceptor 源码
  - proguard: R8/ProGuard 混淆规则
  - guide: 集成指南
  - all: 全部资源
"""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource

from swagger_mcp.tools.generate import run as generate_run
from swagger_mcp.tools.annotate import run as annotate_run
from swagger_mcp.tools.swaggerlog import (
    get_interceptor_source,
    get_proguard_rules,
    get_guide,
    get_all,
)

server = Server("swagger-mcp")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="swagger_generate",
        description="从 Swagger/OpenAPI JSON 生成可读命名的 Kotlin 代码（suspend + Retrofit2 + kotlinx.serialization，不混淆，增量合并）。支持 URL 或本地文件。",
        inputSchema={
            "type": "object",
            "properties": {
                "swagger_url": {
                    "type": "string",
                    "description": "Swagger JSON URL 或本地文件路径（必填）",
                },
                "package": {
                    "type": "string",
                    "description": "Kotlin 根包名，如 com.myapp.api（必填）",
                },
                "output_dir": {
                    "type": "string",
                    "description": "输出目录（默认 app）",
                },
                "split_by_tag": {
                    "type": "boolean",
                    "description": "按 Swagger tag 拆分多个接口文件（默认 false）",
                },
                "model_names": {
                    "type": "string",
                    "description": "中文模型名→英文类名映射，格式 '原名:EnName,...'（可选）",
                },
            },
            "required": ["swagger_url", "package"],
        },
    ),
    Tool(
        name="swagger_annotate",
        description="基于 Swagger JSON 为 Kotlin Bean 字段自动补充 KDoc 注释。支持 URL 或本地文件，支持预览和 CI 检查模式。",
        inputSchema={
            "type": "object",
            "properties": {
                "swagger_url": {
                    "type": "string",
                    "description": "Swagger JSON URL 或本地文件路径（必填）",
                },
                "beans_dir": {
                    "type": "string",
                    "description": "Kotlin Bean 类所在目录（必填）",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "预览模式：只报告变更，不修改文件（默认 false）",
                },
                "check_only": {
                    "type": "boolean",
                    "description": "CI 检查模式：有缺失注释时返回失败（默认 false）",
                },
            },
            "required": ["swagger_url", "beans_dir"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

RESOURCES = [
    Resource(
        uri="swagger-mcp://swaggerlog/interceptor",
        name="SwaggerLoggingInterceptor.kt",
        description="带 Swagger v2 api-docs 集成的 OkHttp 日志拦截器源码",
        mimeType="text/x-kotlin",
    ),
    Resource(
        uri="swagger-mcp://swaggerlog/proguard",
        name="proguard-rules.pro",
        description="R8/ProGuard 混淆保留规则",
        mimeType="text/plain",
    ),
    Resource(
        uri="swagger-mcp://swaggerlog/guide",
        name="集成指南",
        description="SwaggerLoggingInterceptor 集成步骤、参数说明、陷阱提示",
        mimeType="text/markdown",
    ),
    Resource(
        uri="swagger-mcp://swaggerlog/all",
        name="全部资源",
        description="源码 + ProGuard 规则 + 集成指南（一次性获取）",
        mimeType="text/plain",
    ),
]

_RESOURCE_CONTENT_MAP = {
    "interceptor": get_interceptor_source,
    "proguard": get_proguard_rules,
    "guide": get_guide,
    "all": get_all,
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.list_resources()
async def list_resources() -> list[Resource]:
    return RESOURCES


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # ---- swagger_generate ----
    if name == "swagger_generate":
        swagger_url = arguments.get("swagger_url")
        if not swagger_url:
            return _error("缺少必填参数: swagger_url")
        package = arguments.get("package")
        if not package:
            return _error("缺少必填参数: package")

        result = generate_run(
            swagger_url=swagger_url,
            package=package,
            output_dir=arguments.get("output_dir", "app"),
            split_by_tag=arguments.get("split_by_tag", False),
            model_names=arguments.get("model_names"),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    # ---- swagger_annotate ----
    elif name == "swagger_annotate":
        swagger_url = arguments.get("swagger_url")
        if not swagger_url:
            return _error("缺少必填参数: swagger_url")
        beans_dir = arguments.get("beans_dir")
        if not beans_dir:
            return _error("缺少必填参数: beans_dir")

        result = annotate_run(
            swagger_url=swagger_url,
            beans_dir=beans_dir,
            dry_run=arguments.get("dry_run", False),
            check_only=arguments.get("check_only", False),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


@server.read_resource()
async def read_resource(uri) -> str:
    """读取 swaggerlog 资源。

    URI 格式: swagger-mcp://swaggerlog/{interceptor,proguard,guide,all}
    注: uri 参数类型为 mcp.types.AnyUrl，需转为 str 处理。
    """
    resource_id = _parse_resource_uri(str(uri))
    if resource_id is None or resource_id not in _RESOURCE_CONTENT_MAP:
        raise ValueError(f"Unknown resource: {uri}")
    return _RESOURCE_CONTENT_MAP[resource_id]()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_resource_uri(uri: str) -> str | None:
    """从 URI 提取资源 ID。

    >>> _parse_resource_uri("swagger-mcp://swaggerlog/interceptor")
    'interceptor'
    >>> _parse_resource_uri("swagger-mcp://swaggerlog/guide")
    'guide'
    """
    prefix = "swagger-mcp://swaggerlog/"
    if uri.startswith(prefix):
        return uri[len(prefix):]
    return None


def _error(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"ok": False, "errors": [message]}, ensure_ascii=False))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
