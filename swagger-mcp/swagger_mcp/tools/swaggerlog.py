"""swaggerlog 资源工具 — 获取 SwaggerLoggingInterceptor 源码和配置。"""

from __future__ import annotations

import os

_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "..", "resources")

_GUIDE = """# SwaggerLoggingInterceptor 集成指南

## 是什么

SwaggerLoggingInterceptor 是一个带 Swagger v2 api-docs 集成的 OkHttp 日志拦截器。

核心能力:
- 自动拉取 + 缓存 Swagger 文档（内存 + 文件双层，24h TTL）
- JSON 字段反混淆：用 description 中的 "原始名:描述" 映射还原字段名
- 可选字段过滤 + Pretty-print 格式化
- 大日志分段（超 3000 字符自动 chunked）

## 集成三步

### 1. 定义 facade 接口
```kotlin
interface RaucidGoogleInterceptor {
    fun getInterceptor(): Interceptor?
}
```

### 2. Source Set 二选一
- noGoogle/: 实例化 SwaggerLoggingInterceptor 返回
- google/: return null（生产包不注入）

### 3. OkHttp 绑定
```kotlin
OkHttpClient.Builder()
    .addInterceptor(RaucidGoogleServices.interceptor.getInterceptor())
```

## 构造函数参数

| 参数 | 类型 | 说明 |
|------|------|------|
| baseUrl | String | API 基础 URL |
| swaggerDocUrl | String | Swagger v2 api-docs 地址 |
| deobfus | Boolean | 是否反混淆 JSON 字段名 |
| filter | Boolean | 是否过滤未定义字段 |
| format | Boolean | 是否 pretty-print |
| tagPrefix | String | 日志 tag 前缀 |
| cacheFile | () -> File? | 缓存目录工厂（lambda 延迟求值） |
| log | (LogLevel, String, String) -> Unit | 日志输出回调 |

## Swagger 字段映射约定

```json
{
  "definitions": {
    "SomeModel": {
      "properties": {
        "a": { "description": "userName:用户姓名" }
      }
    }
  }
}
```
description 冒号前为原始字段名，冒号后为中文说明。
反混淆时 "a" → "userName"。

## 关键陷阱

1. cacheFile 必须用 lambda 延迟求值
2. 响应体 > 1MB 跳过内容读取
3. 非 JSON 请求体仅输出摘要
4. 缓存损坏不阻断请求（降级输出原始日志）
5. R8 混淆需要 keep 规则（见 proguard-rules.pro）
"""


def get_interceptor_source() -> str:
    """返回 SwaggerLoggingInterceptor.kt 完整源码。"""
    path = os.path.join(_RESOURCES_DIR, "SwaggerLoggingInterceptor.kt")
    with open(path, encoding="utf-8") as f:
        return f.read()


def get_proguard_rules() -> str:
    """返回 R8/ProGuard 混淆规则。"""
    path = os.path.join(_RESOURCES_DIR, "proguard-rules.pro")
    with open(path, encoding="utf-8") as f:
        return f.read()


def get_guide() -> str:
    """返回集成指南。"""
    return _GUIDE


def get_all() -> str:
    """返回所有资源：源码 + ProGuard 规则 + 指南。"""
    parts = [
        "=" * 60,
        "SwaggerLoggingInterceptor.kt",
        "=" * 60,
        get_interceptor_source(),
        "",
        "=" * 60,
        "proguard-rules.pro",
        "=" * 60,
        get_proguard_rules(),
        "",
        "=" * 60,
        "集成指南",
        "=" * 60,
        get_guide(),
    ]
    return "\n".join(parts)
