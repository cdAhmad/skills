---
name: "swagger_annotate"
version: "1.1.0"
description: "基于 Swagger JSON 为 Kotlin Bean 类自动补充注释。触发场景：(1) 为混淆后的 Kotlin data class 字段补充 Swagger 中文注释，(2) CI 检查 Bean 类注释是否完整，(3) 更新 Swagger 缓存后刷新字段注释，(4) 排查字段→定义匹配问题，(5) 处理 Swagger v2 api-docs 字段映射规则。"
---

# Swagger Annotate — 自动注释 Kotlin Bean 类

## 是什么

`annotate_beans.py` 是一个 Python 脚本，根据 Swagger v2 `api-docs` JSON 自动为混淆后的 Kotlin Bean（data class）字段补充 `/** 中文描述 */` 注释。

核心能力：
- **字段名自动匹配**：通过 Swagger property key（即混淆后的字段名）与 Kotlin 字段名精确对应
- **类级别 KDoc 生成**：根据 Swagger paths 信息自动生成 `@param` / 接口地址注释
- **手动映射兜底**：`MANUAL_COMMENTS` 字典覆盖 Swagger 未定义的通用类，由使用者按需维护
- **CI 检查模式**：`--check-only` 模式下有缺失注释则 exit 1

---

## 用法

```bash
# 指定 api-docs URL（每次临时下载，用完即删）
python .claude/skills/swagger_annotate/scripts/annotate_beans.py \
    --input https://example.com/v2/api-docs \
    --beans-dir app/src/main/java/com/example/been

# 也支持 Swagger UI 地址（自动截取域名拼接 /v2/api-docs）
python .claude/skills/swagger_annotate/scripts/annotate_beans.py \
    --input https://example.com/doc.html#/default/xxx \
    --beans-dir app/src/main/java/com/example/been

# 指定本地 JSON 文件
python .claude/skills/swagger_annotate/scripts/annotate_beans.py \
    --input swagger.json \
    --beans-dir app/src/main/java/com/example/been

# 试运行（仅预览，不写入文件）
python .claude/skills/swagger_annotate/scripts/annotate_beans.py \
    --input swagger.json --beans-dir app/src/main/java/com/example/been --dry-run

# CI 检查模式（有缺失注释时 exit 1）
python .claude/skills/swagger_annotate/scripts/annotate_beans.py \
    --input swagger.json --beans-dir app/src/main/java/com/example/been --check-only
```

---

## 脚本文件

| 文件 | 用途 |
|------|------|
| `scripts/annotate_beans.py` | 主入口：遍历 Kotlin 文件、匹配 Swagger 字段、应用注释 |
| `scripts/swagger_annotate/parser.py` | Swagger JSON 解析：扁平映射、字段集匹配、definition→路径关联 |
| `scripts/swagger_annotate/kt_annotator.py` | Kotlin 文件解析：data class 字段提取、KDoc 生成、注释替换 |

---

## Swagger 字段映射约定

脚本依赖 Swagger definitions 中 `description` 字段的特定格式来提取中文注释：

```json
{
  "definitions": {
    "ApplyOrderResp": {
      "properties": {
        "a": { "type": "string", "description": "userName:用户姓名" },
        "b": { "type": "integer", "description": "orderAmount:订单金额:元" }
      }
    }
  }
}
```

- `description` 冒号后的部分为**中文描述**（= 注释内容）
- `description` 冒号前的第一个英文标识符为**原始字段名**（用于类 KDoc 上下文）
- 多层前缀（`a:b:描述`）时贪婪剥离所有英文标识符，剩余中文部分作为描述
- 注释输出：若原始字段名 ≠ 混淆字段名，输出 `/** userName: 用户姓名 */`；否则输出 `/** 用户姓名 */`

---

## 匹配策略

### 字段级匹配

Swagger property **key** 就是混淆后的字段名，与 Kotlin 字段名一致 → 直接通过字段名从扁平映射中查找。

### 类级匹配（生成类 KDoc 时）

通过字段名集合匹配 Kotlin class → Swagger definition：

1. **精确匹配**：Kotlin 字段集 == Swagger definition 字段集（frozenset 相等）
2. **模糊匹配**：Jaccard 相似度最高且覆盖率 ≥ 50% 的 definition
3. **无匹配**：仅从手动映射获取 KDoc

---

## 手动映射

`MANUAL_COMMENTS` 字典位于 `scripts/annotate_beans.py` 顶部，覆盖 Swagger 未定义的通用类：

```python
MANUAL_COMMENTS: dict[str, dict] = {
    # 格式示例:
    # "ClassName": {
    #     "class_kdoc": "/**\n * 类描述\n */",
    #     "fields": {"fieldName": "字段描述"},
    # },
}
```

- `class_kdoc`：完整的类级 KDoc 字符串（含 `/**` `*/`）
- `fields`：`{字段名 → "中文描述"}` 映射
- 手动映射优先级高于 Swagger 匹配

---

## 数据源配置

`--input` 同时接受 URL 和本地文件路径，脚本自动识别。

不传 `--input` 时，按以下优先级查找：

1. **环境变量** `SWAGGER_API_DOCS` — URL 或文件路径
2. **配置文件** `tools/swagger_sources.json`（不入库）：

```json
{
    "default": "https://example.com/v2/api-docs"
}
```

`"default"` 的值可以是 URL 或本地文件路径，例如：

```json
{"default": "/path/to/swagger.json"}
```


---

## 注释生成规则

### 字段注释

- **已有 KDoc 且描述不含原始字段名** → 补充原始字段名前缀
- **有 `//fl` 占位符** → 替换为标准 KDoc
- **行尾 `// 注释`** → 迁移到上方 `/** 注释 */`
- **无任何注释** → 插入新的 `/** 描述 */`

### 类级 KDoc

- 仅当类缺少 KDoc 时生成
- 格式：`/** 接口参数对象：{summary}\n * 接口地址：{path} */`

---

## 关键陷阱

### 1. 脚本路径与项目根目录

脚本位于 `.claude/skills/swagger_annotate/scripts/` 深层目录，内部通过向上查找 `.git` 自动定位项目根目录。从项目根目录或任意子目录执行均可。

### 2. R8 混淆下的字段名一致性

脚本假定 Swagger property key（混淆名）与 Kotlin 编译后字段名一致。确保 Swagger JSON 由混淆后的 APK 生成，而非源码阶段导出。

### 3. 字段集匹配的局限性

模糊匹配仅依赖字段名集合的重叠度，当多个 definition 字段集相似时，匹配可能不准确。遇到这种情况应在 `MANUAL_COMMENTS` 中手动指定。

### 4. 不处理嵌套泛型

`kt_annotator.py` 解析字段类型时保留完整泛型参数（如 `List<Map<String, Int>>`），但不解析嵌套 data class 的内部结构。

---

## 常见问题排查

| 现象 | 可能原因 | 排查步骤 |
|------|----------|----------|
| 字段无注释 | Swagger definitions 中无此字段 | 检查 JSON 中是否有对应 property key |
| 类 KDoc 不准确 | 字段集匹配到错误的 definition | `--dry-run` 预览，在 `MANUAL_COMMENTS` 中手动指定 `class_kdoc` |
| `ERROR: directory not found` | beans 目录路径不正确 | `--beans-dir` 为必填参数，请指定正确的 Kotlin Bean 类目录 |
| 缓存过期未更新 | 网络不可达或 URL 变更 | `curl` Swagger URL 确认可访问，或手动 `--input` 指定本地文件 |
| CI 检查失败 | 有字段缺注释 | `--dry-run` 查看缺失项，补充 Swagger 字段或手动映射 |

---

## 不适用场景

- **Swagger v3 / OpenAPI 3.0** → parser 按 v2 格式解析，需调整 `parser.py` 适配 `openapi`/`components/schemas` 结构
- **Kotlin 非 data class** → `kt_annotator.py` 的 `_parse_multi_line_fields` 依赖于构造函数参数模式
- **Java Bean 类** → 完全不同的解析逻辑，需另写 parser
