---
name: swagger-generate-interface
description: 从 Swagger/OpenAPI JSON 生成 Kotlin 接口 + 模型代码（suspend + Retrofit2 + kotlinx.serialization，不混淆命名，支持增量合并）。纯 Python 实现。触发场景：(1) 从 Swagger URL 或本地 JSON 生成 Kotlin API 客户端，(2) 在已有接口/模型上追加新方法/字段，(3) 按 tag 拆分接口文件。
---

# swagger-generate-interface

纯 Python 实现的 Swagger → Kotlin 代码生成器。零第三方依赖，不混淆命名，生成可读的 Kotlin 代码。

## Agent 执行流程

### 0. 前置检查

- 确认 `python3 --version` >= 3.10，否则提示用户升级

### 1. 确认必填参数

询问用户两个必填参数：

| 参数 | 建议值 | 说明 |
|------|--------|------|
| `--swaggerApiUrl` | - | Swagger JSON URL 或本地文件路径 |
| `--package` | 项目根包名（如 `com.myapp.api`） | Kotlin 代码的 package |

### 2. 可选参数

全部使用默认值。仅在用户明确指定时才覆盖：

- 用户说"按模块拆分" → `--splitByTag true`
- 用户说"输出到 xxx 目录" → `--outputDir xxx`

### 3. 定位并进入 skill 目录

优先 `~/.claude/skills/swagger-generate-interface`，其次项目内 `skills/swagger-generate-interface`。若都不存在则报错。

```bash
if [ -d ~/.claude/skills/swagger-generate-interface ]; then
  cd ~/.claude/skills/swagger-generate-interface
elif [ -d skills/swagger-generate-interface ]; then
  cd skills/swagger-generate-interface
else
  echo "错误: 找不到 swagger-generate-interface skill 目录"
  exit 1
fi
```

### 4. 运行生成

```bash
python3 scripts/main.py \
  --swaggerApiUrl "..." \
  --package "..."
```

### 5. 中文模型名处理

如果 Swagger definition 包含中文名（如 `用户信息`），脚本会用哈希自动生成英文类名（如 `Model_426c4548`）并打印警告。Agent 应在运行前：

1. 扫描 Swagger JSON 的 `definitions` 字段，找出非 ASCII 的模型名
2. 直接翻译为英文（注意检查是否与已有类名重复）
3. 通过 `--modelNames` 参数传入：`--modelNames "用户信息:UserInfo,订单数据:OrderData"`
4. 生成的类 KDoc 会记录 `Swagger 原始名: 用户信息`，后续运行自动从 KDoc 恢复映射

### 6. 处理结果

| 输出关键字 | 状态 | Agent 应做 |
|-----------|------|-----------|
| `All operations completed` | ✅ 成功 | 报告生成路径、模型数量 |
| `[generated]` | ✅ 新建 | 告知用户新建了哪些文件 |
| `[updated]` | ✅ 增量 | 告知用户追加了多少字段/方法 |
| `[skipped]` | ⏭️ 跳过 | 告知用户无变更，已跳过 |
| `⚠ 模型名 ... 使用了自动名称` | ⚠️ 有哈希名 | 翻译中文名 → `--modelNames "原名:EnName,..."` 重跑 |
| `检测到 N 个非 ASCII 模型名` | ⚠️ 同上 | 直接在首次运行时就加上 `--modelNames` |
| `Code generation failed` | ❌ 失败 | 展示错误堆栈，建议检查 Swagger 格式 |
| `Error:` 开头 | ❌ 参数错误 | 根据提示修正参数后重试 |

## 命令行参考

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--swaggerApiUrl` | **(必填)** | Swagger JSON URL 或本地文件路径 |
| `--package` | **(必填)** | 根包名（如 `com.myapp.api`） |
| `--outputDir` | `app` | 输出目录 |
| `--sourceFolder` | `src/main/kotlin` | 源码子目录 |
| `--splitByTag` | `false` | 按 tag 拆分多个接口文件 |
| `--baseResponse` | `BaseResponse` | 响应包装类名 |
| `--modelNames` | (空) | 中文模型名→英文映射，格式 `"原名:EnName,..."` |

## 典型场景

### 首次生成（URL）
```bash
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --package "com.myapp.api"
```

### 首次生成（本地文件）
```bash
python3 scripts/main.py \
  --swaggerApiUrl "./swagger.json" \
  --package "com.myapp.api"
```

### 指定输出目录
```bash
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --package "com.myapp.api" \
  --outputDir "./app"
```

### 增量追加（接口变更后，直接重跑即可）
```bash
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --package "com.myapp.api"
```

### 按业务模块拆分
```bash
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --package "com.myapp.api" \
  --splitByTag true
```

## 生成产物

```
<outputDir>/
└── src/main/kotlin/<package>/
    ├── model/
    │   ├── BaseResponse.kt
    │   └── *.kt              ← @Serializable data class
    └── api/
        └── ApiService.kt     ← suspend fun + Retrofit2 接口
```

## 关键行为

- **不混淆命名**：模型名、方法名、字段名直接使用 Swagger 原文，生成的代码可读性高
- **增量合并**：读取已有 `.kt` 文件，只追加新增的字段/方法，从不修改或删除已有代码
- **字段注释**：仿照 swagger_annotate 的单行 KDoc 风格（`/** originalName: 中文描述 */`）
- **响应包装器剥离**：自动检测并移除具有 `code` + `msg` 属性的响应包装器模型
- **公共 Header**：出现率 >= 90% 的 header 参数自动识别为公共 header，生成 `ApiHeaders.createHeaders()` 方法
- **纯内存管道**：不写任何中间文件（无 `api_gen/`、无日志、无缓存）

## 生成代码特征

- `suspend fun` + Retrofit2 注解（`@GET/@POST/@PUT/@DELETE/@Multipart`）
- `@Serializable data class` + 条件 `@SerialName`（字段名与 JSON key 不同时才生成）
- 每字段上方 `/** originalName: 中文描述 */` 单行 KDoc 注释
- 每 API 方法 KDoc 含描述 + HTTP 路径 + 所有响应码
- 文件上传生成 `@Part okhttp3.MultipartBody.Part`

## 与 apiGen 的区别

| | apiGen | swagger-generate-interface |
|---|---|---|
| 命名 | SHA-256 混淆 | Swagger 原文 |
| 参数数量 | 17 个 | 6 个（2 必填） |
| 元数据文件 | api_gen/ + logs/ + history/ | 无 |
| MD5 缓存 | 有 | 无（每次都重新生成） |
| 模型名映射 | 需要 model_name_mapping.json | 不需要 |

## 注意事项

- 需要 Python 3.10+，无需 pip install，直接运行脚本即可
- 生成的代码使用原始 Swagger 名称，如果 Swagger 中有特殊字符，`_safe_name()` 会自动处理
- 增量合并基于名称匹配：如果手动重命名了已有的方法/字段，重跑会追加新方法/字段而不是覆盖
