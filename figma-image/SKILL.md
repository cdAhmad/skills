---
name: figma-image
description: 从 Figma 设计稿下载 4x PNG 并生成 Android 各密度 WebP。触发：(1) 提供 Figma 链接下载图片，(2) 生成 mipmap 图标，(3) 从 Figma 导出资源。
---

# Figma / 本地图片 → Android WebP

从 Figma 下载 4x PNG，或使用本地 PNG/文件夹，通过 `scripts/generate_mipmap_webp.py` 生成各密度 mipmap WebP（保持宽高比）。默认输出到当前工作目录（Android 项目根目录）的 `app/src/main/res/`。

## 交互流程

当用户调用此 skill 时，按以下步骤执行：

### 1. 确定图片来源

询问用户 PNG 下载文件夹路径（如 `~/Downloads/figma-images/`），用户只需提供一次，后续调用复用该路径。**路径可通过项目 memory 或 CLAUDE.md 记住。**

### 2. 扫描文件夹

主动搜索文件夹下的 `.png` / `.jpg` / `.jpeg` / `.webp` 文件，列出所有待处理图片：

```
发现 3 张图片:
  1. icon_home.png
  2. icon_settings.png
  3. splash_bg.png
```

### 3. 确认输出名称

逐张展示文件名（去掉扩展名）作为默认输出名，询问用户是否需要重命名：

```
icon_home → 输出名 "icon_home" ？或输入新名称 / 跳过
```

- 直接回车 → 使用默认名称
- 输入新名称 → 使用自定义名称
- 输入 `skip` → 跳过该图片

### 4. 确认目标宽度

询问用户是否需要指定 xxxhdpi 目标宽度：

- 图标类：建议 `--target-width 192`（mdpi=48dp）
- 全屏图/背景：不传 `--target-width`，使用源图宽度

### 5. 执行生成

对每张确认的图片调用脚本生成各密度 WebP，处理完成后自动清理源 PNG。**命令在 Android 项目根目录执行**，WebP 自动输出到 `app/src/main/res/mipmap-*/`。

```bash
python3 skills/figma-image/scripts/generate_mipmap_webp.py \
  "<folder>/icon_home.png" icon_home --target-width 192
```

## 密度比例

| 密度 | 相对于 xxxhdpi 的缩放 |
| --- | --- |
| mdpi | × 1/4 (0.25) |
| hdpi | × 1.5/4 (0.375) |
| xhdpi | × 2/4 (0.5) |
| xxhdpi | × 3/4 (0.75) |
| xxxhdpi | × 1.0（目标宽度） |

## 脚本参数

| 参数 | 必传 | 说明 |
| --- | --- | --- |
| 图片源 | ✅ | Figma URL、本地 PNG 路径、或本地文件夹路径 |
| 输出文件名 | ✅ | 输出文件名（不含扩展名，输出为 .webp）。文件夹模式下作为前缀 `{name}_{原文件名}` |
| --target-width | 可选 | xxxhdpi 目标宽度(px)，高度按原图比例自动计算。不传则使用源图宽度 |
| --res-dir | 可选 | Android res 输出目录，默认为当前工作目录下的 `app/src/main/res` |
| --download-dir | 可选 | Figma 下载目录，默认为 `scripts/downloads/` |
| --token | 可选 | Figma API Token（优先级：命令行 > 环境变量 `FIGMA_TOKEN` > 项目根 `.figma_token_tmp`） |
| --no-cleanup | 可选 | 保留源文件，不自动清理。默认处理完成后删除源文件，避免下次重复处理 |

## 命令参考

> **注意**：在 Android 项目根目录执行，WebP 自动输出到 `app/src/main/res/`。

```bash
# 单张本地图片
python3 skills/figma-image/scripts/generate_mipmap_webp.py \
  ~/Downloads/figma/icon_home.png icon_home --target-width 192

# Figma URL 下载并转换
python3 skills/figma-image/scripts/generate_mipmap_webp.py \
  "<FIGMA_URL>" icon_name --target-width 192

# 文件夹批量（自动命名）
python3 skills/figma-image/scripts/generate_mipmap_webp.py \
  ~/Downloads/figma/ icon --target-width 192

# 指定输出目录
python3 skills/figma-image/scripts/generate_mipmap_webp.py \
  image.png icon --res-dir /path/to/project/app/src/main/res

# 保留源文件不清理
python3 skills/figma-image/scripts/generate_mipmap_webp.py \
  image.png icon --no-cleanup
```

## Figma Token

FIGMA_TOKEN 已全局配置（环境变量），无需手动传入 `--token`。

## 输出目录

默认输出到当前工作目录下：

```
<CWD>/app/src/main/res/
├── mipmap-mdpi/{output_name}.webp
├── mipmap-hdpi/{output_name}.webp
├── mipmap-xhdpi/{output_name}.webp
├── mipmap-xxhdpi/{output_name}.webp
└── mipmap-xxxhdpi/{output_name}.webp
```

可通过 `--res-dir` 指定其他 Android 项目的 res 路径。Figma 下载的 4x PNG 默认保存在 `scripts/downloads/`，处理完成后自动清理。
