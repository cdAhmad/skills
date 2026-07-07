"""统一 Swagger JSON 加载 — 支持 URL 和本地文件。

合并自:
- swagger-generate-interface/scripts/swagger_loader.py
- swagger_annotate/scripts/annotate_beans.py (get_swagger_path)
- swagger-interface-migration/scripts/swagger_replace.py (fetch_json)
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from urllib.parse import urlparse


def _is_url(s: str) -> bool:
    return bool(urlparse(s).scheme in ("http", "https"))


def _normalize_swagger_url(url: str) -> str:
    """将 Swagger UI 地址自动转换为 /v2/api-docs 端点。"""
    parsed = urlparse(url)
    path = parsed.path.lower()

    if path.endswith("/v2/api-docs") or path.endswith("/v3/api-docs"):
        return url

    if any(kw in path for kw in ("doc.html", "swagger-ui")):
        return f"{parsed.scheme}://{parsed.netloc}/v2/api-docs"

    if path in ("", "/"):
        return f"{parsed.scheme}://{parsed.netloc}/v2/api-docs"

    return url


def load_swagger(source: str) -> dict:
    """从 URL 或本地文件加载 Swagger JSON，返回 parsed dict。

    - URL: 自动处理 doc.html → /v2/api-docs 转换，下载到临时文件
    - 本地: 直接读取 JSON 文件
    - 失败抛出 RuntimeError
    """
    if _is_url(source):
        return _download(source)

    path = os.path.abspath(source)
    if not os.path.isfile(path):
        raise RuntimeError(f"文件不存在: {path}")
    return _load_file(path)


def _load_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _download(url: str) -> dict:
    url = _normalize_swagger_url(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "swagger-mcp/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except Exception as e:
        raise RuntimeError(f"下载 Swagger JSON 失败: {e}") from e


def download_to_tempfile(url: str) -> str:
    """下载 Swagger JSON 到临时文件，返回临时文件路径。调用方负责清理。"""
    url = _normalize_swagger_url(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "swagger-mcp/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="swagger_v2_")
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(data)
        return tmp_path
    except Exception as e:
        raise RuntimeError(f"下载 Swagger JSON 失败: {e}") from e
