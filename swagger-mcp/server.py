#!/usr/bin/env python3
"""swagger-mcp — Swagger 辅助工具 MCP Server。

提供 3 个 tool:
- swagger_generate: Swagger → Kotlin 代码生成（可读命名，增量合并）
- swagger_annotate: 为 Kotlin Bean 字段补充 KDoc 注释
- swaggerlog_get_resource: 获取 SwaggerLoggingInterceptor 源码和配置
"""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from swagger_mcp.tools.generate import run as generate_run
from swagger_mcp.tools.annotate import run as annotate_run
from swagger_mcp.tools.swaggerlog import (
    get_interceptor_source,
    get_proguard_rules,
    get_guide,
    get_all,
)

server = Server("swagger-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
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
                        "default": "app",
                    },
                    "split_by_tag": {
                        "type": "boolean",
                        "description": "按 Swagger tag 拆分多个接口文件（默认 false）",
                        "default": False,
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
                        "default": False,
                    },
                    "check_only": {
                        "type": "boolean",
                        "description": "CI 检查模式：有缺失注释时返回失败（默认 false）",
                        "default": False,
                    },
                },
                "required": ["swagger_url", "beans_dir"],
            },
        ),
        Tool(
            name="swaggerlog_get_resource",
            description="获取 SwaggerLoggingInterceptor 相关资源：拦截器源码、ProGuard 规则、集成指南。",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource": {
                        "type": "string",
                        "description": "要获取的资源类型",
                        "enum": ["interceptor", "proguard", "guide", "all"],
                        "default": "all",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "swagger_generate":
        result = generate_run(
            swagger_url=arguments["swagger_url"],
            package=arguments["package"],
            output_dir=arguments.get("output_dir", "app"),
            split_by_tag=arguments.get("split_by_tag", False),
            model_names=arguments.get("model_names"),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "swagger_annotate":
        result = annotate_run(
            swagger_url=arguments["swagger_url"],
            beans_dir=arguments["beans_dir"],
            dry_run=arguments.get("dry_run", False),
            check_only=arguments.get("check_only", False),
        )
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "swaggerlog_get_resource":
        resource = arguments.get("resource", "all")
        if resource == "interceptor":
            text = get_interceptor_source()
        elif resource == "proguard":
            text = get_proguard_rules()
        elif resource == "guide":
            text = get_guide()
        else:
            text = get_all()
        return [TextContent(type="text", text=text)]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
