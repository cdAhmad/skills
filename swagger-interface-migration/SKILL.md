---
name: swagger-interface-migration
description: Swagger 接口/字段名迁移工具。从 Swagger JSON 的 description 字段中提取替换规则，并在整个代码库中批量将旧名称替换为新名称。当用户需要基于 Swagger 文档进行接口名/字段名批量替换、代码迁移、API 升级时使用。触发场景包括：(1) 使用 Swagger 规范升级 API，(2) 根据 Swagger description 重命名接口/字段，(3) 由 Swagger JSON 驱动的批量代码迁移。
---

# Swagger 接口迁移

通过解析 Swagger JSON 的 `description` 字段，提取替换规则，批量迁移代码库中的接口名和字段名。

JSON 源支持**本地文件路径**或**网络地址（http/https）**两种方式。

对于网络地址，如果传入的是基础域名（无路径或路径为 `/`），脚本会自动拼接 `/v2/api-docs`：

```
http://api.example.com       →  http://api.example.com/v2/api-docs
http://api.example.com/      →  http://api.example.com/v2/api-docs
http://api.example.com/custom/path  →  保持不变
```

## 工作原理

1. 解析 Swagger JSON，收集所有 `description` 字符串。
2. 从 description 中提取 `旧名称:新名称` 映射关系（格式：`前缀:旧值:新值`）。
3. 按 `新值` 去重，保留最后出现的规则。
4. 将有效规则写入 `replace.txt`，未匹配项（旧值为 `null`）写入 `not_found.txt`。
5. 在目标目录中递归扫描所有文本文件，执行 `旧名称` -> `新名称` 的批量替换。

## 前置条件

Swagger JSON 中的 `description` 字段必须遵循以下冒号分隔格式：

```
前缀:旧接口名:新接口名
```

- `前缀` — 任意标签，不参与替换，仅用于标识。
- `旧接口名` — 在代码库中需要被替换的字符串。
- `新接口名` — 用于替换旧接口名的新字符串。
- 如果 `旧接口名` 为 `null`，则该规则仅记录到 `not_found.txt`，不参与替换。

## 使用方法

> **注意**：以下命令在 `swagger-interface-migration/` 目录下执行，脚本位于 `scripts/swagger_replace.py`。

### 推荐流程

**第一步：预览（dry-run）**

在正式替换前，先预览会改哪些文件，确认规则无误：

```bash
# 使用本地 JSON 文件
python scripts/swagger_replace.py -j swagger.json -d <目标目录> --dry-run

# 使用基础域名（自动拼接 /v2/api-docs）
python scripts/swagger_replace.py -j http://api.example.com -d <目标目录> --dry-run

# 使用完整网络地址
python scripts/swagger_replace.py -j http://api.example.com/v2/api-docs -d <目标目录> --dry-run
```

**第二步：实际替换**

确认预览结果无误后，去掉 `--dry-run` 执行实际替换：

```bash
# 使用本地 JSON 文件
python scripts/swagger_replace.py -j swagger.json -d <目标目录>

# 使用基础域名（自动拼接 /v2/api-docs）
python scripts/swagger_replace.py -j http://api.example.com -d <目标目录>

# 使用完整网络地址
python scripts/swagger_replace.py -j http://api.example.com/v2/api-docs -d <目标目录>
```

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-j, --json` | Swagger JSON 文件路径或网络 URL（支持 `http`/`https`） | 必填 |
| `-d, --directory` | 需要执行替换操作的代码根目录 | 必填 |
| `--dry-run` | 预览模式：只显示会替换的内容，不修改实际文件 | 关闭 |
| `--no-word-boundary` | 禁用词边界匹配。禁用后使用简单字符串匹配，可能误替换子字符串 | 开启 |

### 输出文件

| 文件 | 内容 |
|------|------|
| `<目标目录>/replace.txt` | 所有有效的 `旧值|新值` 替换规则（每行一条） |
| `<目标目录>/not_found.txt` | 旧值为 `null` 的规则（被跳过） |

## 脚本行为说明

- **词边界匹配（默认开启）**：使用正则 `\bold\b` 进行替换，避免 `user` 替换时误伤 `username`。
- **预览模式（--dry-run）**：不修改任何文件，只输出会受影响的内容和替换详情。
- 自动跳过二进制文件和图片：`.jar`、`.class`、`.png`、`.jpg`、`.gif`、`.ico`、`.bin`、`.zip`、`.rar`、`.exe`。
- 自动跳过目录：`.git`、`.gradle`、`.idea`、`build`、`gradle`。
- 跳过中间文件 `replace.txt` 和 `not_found.txt`，避免误替换。
- 每次修改文件后，会在终端输出文件路径和替换次数。

## 注意事项

- **强烈建议先使用 `--dry-run` 预览**，审查 `replace.txt` 中的规则是否正确，确认无误后再执行实际替换。
- 脚本直接修改原文件，运行前请确保代码已提交到版本控制。
- 去重策略：当多个 description 共享相同的 `新接口名` 时，保留**最后出现**的那一条规则。
- 输出文件 `replace.txt` 和 `not_found.txt` 会生成在 `-d` 指定的目标目录下。
