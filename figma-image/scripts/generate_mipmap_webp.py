#!/usr/bin/env python3
"""
从 Figma 4x 导出图或本地图片生成各密度 WebP 图标。

用法:
    python3 generate_mipmap_webp.py <图片路径或Figma URL> <输出文件名> [选项]
    python3 generate_mipmap_webp.py <文件夹路径> <输出文件名> [选项]

参数:
    <图片路径/Figma URL/文件夹>  本地图片路径、Figma 设计稿链接、或包含图片的文件夹
    <输出文件名>                 输出文件名 (不含扩展名)

选项:
    --target-width N   xxxhdpi 目标宽度(px)，高度按原图比例缩放，默认使用源图宽度
    --token TOKEN      Figma API Token（也可设环境变量 FIGMA_TOKEN，或项目根 .figma_token_tmp）
    --download-dir DIR Figma 下载目录，默认为当前目录下的 downloads/
    --res-dir DIR      Android res 输出目录，默认为当前工作目录下的 app/src/main/res
    --no-cleanup       保留源文件，不自动清理（默认处理完成后删除源文件以避免重复处理）

密度比例 (以 xxxhdpi=4x 为基准):
    mdpi    = xxxhdpi × 1/4
    hdpi    = xxxhdpi × 1.5/4
    xhdpi   = xxxhdpi × 2/4
    xxhdpi  = xxxhdpi × 3/4
    xxxhdpi = 目标宽度 (默认源图宽度)

示例:
    # 图标：指定 xxxhdpi 宽 192px → 各密度等比缩放
    python3 generate_mipmap_webp.py /tmp/logo.png logo --target-width 192

    # 全屏图：不传宽度，源图直出到 xxxhdpi
    python3 generate_mipmap_webp.py /tmp/splash.png splash_bg

    # Figma URL 直下
    python3 generate_mipmap_webp.py "https://www.figma.com/design/xxx?node-id=123" logo

    # 文件夹批量处理（处理文件夹内所有 PNG/JPG）
    python3 generate_mipmap_webp.py /path/to/images/ icon --target-width 192

    # 指定 Figma 下载目录
    python3 generate_mipmap_webp.py "https://www.figma.com/design/xxx?node-id=123" logo --download-dir ~/Downloads/figma/
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from PIL import Image

# 各密度相对于 xxxhdpi (4x) 的缩放比例
DENSITY_RATIO = {
    "mdpi": 1 / 4,
    "hdpi": 1.5 / 4,
    "xhdpi": 2 / 4,
    "xxhdpi": 3 / 4,
    "xxxhdpi": 1.0,
}

# 支持的图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

FIGMA_API = "https://api.figma.com/v1"


def get_res_base(res_dir: str | None = None) -> str:
    """获取 Android res 输出目录。默认 CWD + app/src/main/res。"""
    if res_dir:
        return os.path.abspath(os.path.expanduser(res_dir))
    return os.path.join(os.getcwd(), "app", "src", "main", "res")

# 默认 Figma 下载目录
DEFAULT_DOWNLOAD_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "downloads"
)


def parse_figma_url(url: str) -> tuple[str, str] | None:
    m = re.match(
        r"https?://(?:www\.)?figma\.com/(?:design|file)/([a-zA-Z0-9]+)/.*[?&]node-id=([0-9]+(?:[-][0-9]+)?)",
        url
    )
    if not m:
        return None
    file_key = m.group(1)
    node_id = m.group(2).replace("-", ":")
    return file_key, node_id


def download_from_figma(file_key: str, node_id: str, token: str, download_dir: str) -> str:
    """从 Figma 导出 4x PNG，保存到下载目录。"""
    export_url = f"{FIGMA_API}/images/{file_key}?ids={node_id}&format=png&scale=4"
    req = urllib.request.Request(export_url, headers={"X-Figma-Token": token})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
        image_url = data["images"].get(node_id)
        if not image_url:
            node_keys = list(data["images"].keys())
            image_url = data["images"][node_keys[0]] if node_keys else None
        if not image_url:
            raise RuntimeError(f"Figma 未返回图片 URL: {data}")

    os.makedirs(download_dir, exist_ok=True)
    out_path = os.path.join(download_dir, f"figma_{node_id.replace(':', '-')}.png")

    urllib.request.urlretrieve(image_url, out_path)
    if os.path.getsize(out_path) == 0:
        # retry with stream read
        req2 = urllib.request.Request(image_url)
        with urllib.request.urlopen(req2) as resp2:
            with open(out_path, "wb") as f:
                f.write(resp2.read())

    return out_path


def calc_size(src_w: int, src_h: int, ratio: float, target_w: int) -> tuple[int, int]:
    """计算目标尺寸，保持原图宽高比。"""
    w = round(target_w * ratio)
    h = round(w * src_h / src_w)
    return w, h


def process_image(img_path: str, output_name: str, target_width: int | None, res_base: str):
    """处理单张图片，生成各密度 WebP。"""
    img = Image.open(img_path)
    src_w, src_h = img.size

    tw = target_width if target_width else src_w

    if target_width:
        print(f"源图 4x: {src_w}x{src_h} → xxxhdpi 目标宽: {tw}px")
    else:
        print(f"源图 4x: {src_w}x{src_h} → xxxhdpi 使用源图宽度")

    print()

    generated = []
    for density, ratio in sorted(DENSITY_RATIO.items(), key=lambda x: x[1]):
        w, h = calc_size(src_w, src_h, ratio, tw)
        out_dir = os.path.join(res_base, f"mipmap-{density}")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{output_name}.webp")

        resized = img.resize((w, h), Image.LANCZOS)
        resized.save(out_path, "WEBP", quality=85)

        kb = os.path.getsize(out_path) / 1024
        print(f"  mipmap-{density}: {w}x{h} ({kb:.1f}KB)")
        generated.append(out_path)

    return generated


def collect_images(src: str) -> list[str]:
    """收集待处理的图片路径。如果是文件夹则返回文件夹内所有图片。"""
    src_path = Path(src).expanduser().resolve()
    if src_path.is_dir():
        images = sorted([
            str(p) for p in src_path.iterdir()
            if p.suffix.lower() in IMAGE_EXTENSIONS
        ])
        if not images:
            print(f"警告: 文件夹中未找到图片文件: {src_path}")
        return images
    else:
        return [str(src_path)]


def _cleanup_source(img_path: str, no_cleanup: bool):
    """清理源文件，避免下次重复处理。"""
    if no_cleanup:
        print(f"  (保留源文件: {img_path})")
        return
    try:
        os.unlink(img_path)
        print(f"  (已清理: {img_path})")
    except OSError as e:
        print(f"  (清理失败: {img_path}, {e})")


def main():
    # 解析 --token；优先环境变量，其次项目根目录 .figma_token_tmp（已 gitignore）
    token = os.environ.get("FIGMA_TOKEN", "")
    if not token:
        token_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".figma_token_tmp",
        )
        if os.path.isfile(token_file):
            token = open(token_file, encoding="utf-8").read().strip()

    # 解析 --download-dir / --res-dir / --no-cleanup
    download_dir = DEFAULT_DOWNLOAD_DIR
    res_dir = None
    no_cleanup = False

    args = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--token" and i + 1 < len(sys.argv):
            token = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--download-dir" and i + 1 < len(sys.argv):
            download_dir = os.path.expanduser(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--res-dir" and i + 1 < len(sys.argv):
            res_dir = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--no-cleanup":
            no_cleanup = True
            i += 1
        else:
            args.append(sys.argv[i])
            i += 1

    if len(args) < 2:
        print(__doc__)
        sys.exit(1)

    src = args[0]
    output_name = args[1]

    # 解析 --target-width (xxxhdpi 目标宽度)
    target_width = None
    for j, arg in enumerate(args):
        if arg == "--target-width" and j + 1 < len(args):
            target_width = int(args[j + 1])
            break

    res_base = get_res_base(res_dir)
    print(f"输出目录: {res_base}/mipmap-*/")
    print()

    # 判断是否为 Figma URL
    is_figma = src.startswith("https://") and "figma.com" in src

    if is_figma:
        # Figma URL → 下载
        parsed = parse_figma_url(src)
        if not parsed:
            print(f"错误: 无法解析 Figma URL: {src}")
            sys.exit(1)
        if not token:
            print("错误: Figma 需要 Token，请设置 FIGMA_TOKEN、传 --token，或配置项目根 .figma_token_tmp")
            sys.exit(1)

        file_key, node_id = parsed
        print(f"Figma: file={file_key} node={node_id}")
        print(f"下载 4x PNG → {download_dir}/ ...")
        src_path = download_from_figma(file_key, node_id, token, download_dir)
        print(f"下载完成: {src_path}")

        process_image(src_path, output_name, target_width, res_base)
        _cleanup_source(src_path, no_cleanup)
    else:
        # 本地路径：可能是单文件或文件夹
        images = collect_images(src)
        if not images:
            print(f"错误: 未找到可处理的图片: {src}")
            sys.exit(1)

        if len(images) == 1:
            # 单文件
            if not os.path.exists(images[0]):
                print(f"错误: 文件不存在: {images[0]}")
                sys.exit(1)
            process_image(images[0], output_name, target_width, res_base)
            _cleanup_source(images[0], no_cleanup)
        else:
            # 文件夹批量处理
            print(f"文件夹模式: 找到 {len(images)} 张图片")
            total = 0
            for img_path in images:
                stem = Path(img_path).stem
                name = f"{output_name}_{stem}" if output_name else stem
                print(f"\n--- 处理: {os.path.basename(img_path)} → {name} ---")
                generated = process_image(img_path, name, target_width, res_base)
                total += len(generated)
                _cleanup_source(img_path, no_cleanup)
            print(f"\n完成: 共处理 {len(images)} 张图片，生成 {total} 个密度 → {res_base}/mipmap-*/")


if __name__ == "__main__":
    main()