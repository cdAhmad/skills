"""Swagger JSON 加载器 — 支持 URL 下载和本地文件，零缓存"""

from __future__ import annotations

import json
import os
import urllib.request


class SwaggerLoader:
    """加载 Swagger JSON，返回解析后的 dict。不做 MD5 缓存、不做变更检测。"""

    @staticmethod
    def load(url_or_path: str) -> dict | None:
        """从 URL 或本地文件路径加载 Swagger JSON。失败返回 None。"""
        if os.path.isfile(url_or_path):
            return SwaggerLoader._load_file(url_or_path)
        if url_or_path.startswith(("http://", "https://")):
            return SwaggerLoader._download(url_or_path)

        print(f"Error: '{url_or_path}' is not a valid URL or file path")
        return None

    @staticmethod
    def _load_file(path: str) -> dict | None:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading local file: {e}")
            return None

    @staticmethod
    def _download(url: str) -> dict | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "swagger-generate-interface/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except Exception as e:
            print(f"Error downloading Swagger JSON: {e}")
            return None
