---
name: apiGen
description: 将 Swagger/OpenAPI 文档转换为 Kotlin 代码（suspend + Retrofit2 + kotlinx.serialization）。纯 Python 实现。触发：(1) 从 Swagger URL 或本地 JSON 文件生成 Kotlin API 客户端，(2) 接口变更后重新生成，(3) 模型名映射审核与增量更新，(4) 按 tag 拆分接口。
---

# apiGen

纯 Python 实现的 Swagger → Kotlin 代码生成器。零第三方依赖。

## Agent 执行流程

1. **确认必填参数**：询问 `--swaggerApiUrl`、`--salt` 和 `--package`。salt 建议用项目名（如 `myapp`），package 用项目根包名（如 `com.myapp.api`）。缺失则询问用户。
2. **可选参数**：全部使用默认值。仅在用户明确指定时才覆盖（如"包名用 com.xxx"、"按模块拆分"等），无需逐项询问。
3. **进入 skill 目录**：`cd` 到 apiGen 所在目录（项目 `skills/apiGen` 或 `~/.claude/skills/apiGen`）
4. **运行生成**：`python3 scripts/main.py ...`
5. **报告结果**：输出目录、host、生成/跳过状态；如有新模型映射则展示给用户确认

## 命令行参考

> **注意**：以下命令在 apiGen 目录下执行，脚本位于 `scripts/main.py`。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--swaggerApiUrl` | **(必填)** | Swagger JSON URL 或本地文件路径 |
| `--salt` | **(必填)** | 混淆盐值（选定后不可更换） |
| `--outputDir` | `app` | 输出目录 |
| `--package` | **(必填)** | 根包名（如 `com.myapp.api`） |
| `--modelPackage` | `{package}.model` | 模型包名 |
| `--apiPackage` | `{package}.api` | API 包名 |
| `--sourceFolder` | `src/main/kotlin` | 源码子目录 |
| `--splitByTag` | `false` | 按 tag 拆分多接口 |
| `--exportMappingOnly` | `false` | 仅导出映射，不生成代码 |
| `--exportModelNameMap` | `<apiGenDir>/model_name_mapping.json` | 映射导出路径 |
| `--modelNameMap` | - | 固定映射 JSON（增量用，`apiGenDir` 下有 `model_name_mapping.json` 则自动加载） |
| `--disableModelMapping` | `false` | 禁用模型名混淆 |
| `--baseResponseName` | `BaseResponse` | 响应包装类名 |
| `--obfuscateOperationId` | `true` | 混淆 operationId |
| `--apiName` | `ApiService` | 接口名称（`--splitByTag false` 时生效） |
| `--apiGenDir` | `<outputDir>/api_gen` | apiGen 工作目录 |

## 典型场景

### 完整命令（全部参数）
```bash
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --salt "project-unique-salt" \
  --outputDir "./api" \
  --package "com.example.api" \
  --modelPackage "com.example.api.model" \
  --apiPackage "com.example.api.api" \
  --sourceFolder "src/main/kotlin" \
  --baseResponseName "BaseResponse" \
  --apiName "ApiService" \
  --apiGenDir "./api/api_gen" \
  --splitByTag false \
  --obfuscateOperationId true \
  --disableModelMapping false \
  --exportMappingOnly false
```

### 常用组合（指定包名 + 拆分 + 输出到 Android 项目）
```bash
python3 scripts/main.py \
  --swaggerApiUrl "./swagger.json" \
  --salt "project-unique-salt" \
  --package "com.myapp.api" \
  --outputDir "./app" \
  --splitByTag true
```
生成路径：`./app/src/main/kotlin/com/myapp/api/model/` + `./app/src/main/kotlin/com/myapp/api/api/`

### 首次生成（URL）
```bash
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --salt "project-unique-salt" \
  --package "com.myapp.api"
```

### 首次生成（本地文件）
```bash
python3 scripts/main.py \
  --swaggerApiUrl "./swagger.json" \
  --salt "project-unique-salt" \
  --package "com.myapp.api"
```

### 审核模型名后生成
```bash
# step 1: 导出映射（仅导出，不生成代码）
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --salt "project-unique-salt" \
  --package "com.myapp.api" \
  --exportMappingOnly true
# → 编辑 app/api_gen/model_name_mapping.json，审核并修正模型名

# step 2: 直接重跑（自动加载已编辑的 model_name_mapping.json）
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --salt "project-unique-salt" \
  --package "com.myapp.api"
```

### 重新生成（接口变更后）
```bash
# 复用之前的参数，直接重跑即可
# 脚本自动检测变更、输出 diff、保持模型名稳定
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --salt "project-unique-salt" \
  --package "com.myapp.api"
```

### 按业务模块拆分
```bash
python3 scripts/main.py \
  --swaggerApiUrl "https://xxx/v2/api-docs" \
  --salt "project-unique-salt" \
  --package "com.myapp.api" \
  --splitByTag true
```

## 生成产物

```
<outputDir>/
├── src/main/kotlin/<package>/
│   ├── model/
│   │   ├── BaseResponse.kt     ← @Serializable data class BaseResponse<T>
│   │   └── *.kt                ← 含原始名+使用接口+字段描述的注释
│   └── api/
│       └── ApiService.kt       ← suspend fun + KDoc(描述+路径+响应码)
└── api_gen/
    ├── generate.sh              ← 最后成功命令（绝对路径，纳入版本控制）
    ├── command_history.log       ← 所有执行命令及状态（生成成功/跳过/失败）
    ├── model_name_mapping.json  ← 模型名映射（纳入版本控制）
    ├── swagger_update.log       ← 全量变更日志
    ├── logs/
    │   ├── default_OpenAPI.json  ← 下载的原始 Swagger JSON
    │   ├── swagger_old.json      ← 上次 Swagger 快照（用于 diff）
    │   ├── temp.json             ← 清洗混淆后的中间文件
    │   ├── changelog_*.md        ← 每次变更独立报告
    │   ├── common_headers.json   ← 公共 header 列表
    │   └── swagger_md5.txt       ← MD5 缓存
    └── history/
        ├── swagger_*.json        ← Swagger 历史快照
        └── code_<ts>/            ← 旧代码备份
```

## 关键行为

- **命令记录**：每次执行追加 `api_gen/command_history.log`（时间戳 + host + 完整命令 + 执行状态）；生成成功后覆盖 `api_gen/generate.sh`（绝对路径脚本，可直接运行复现）
- **MD5 去重**：Swagger 未变更时跳过生成
- **变更检测**：Swagger 更新时输出字段级 diff（新增/删除参数、返回字段、响应码变更）
- **自动备份**：变更时将旧代码备份到 `api_gen/history/code_<ts>/`
- **模型名稳定**：首次运行导出映射，后续自动加载 `api_gen/model_name_mapping.json`，无需手动指定 `--modelNameMap`
- **新增模型检测**：Swagger 新增 definition 时脚本中断，导出新映射并提示用户确认后再运行
- **公共 Header**：出现率 >= 90% 的 header 参数自动识别为公共 header，生成 `ApiHeaders.createHeaders()` 方法；非公共 header 会被移除（需手动添加 `@Header` 注解）
- **包装器剥离**：自动检测并移除具有 `code` + `msg` 属性的响应包装器模型，释放出真实数据类型

## Agent 处理指引

### 脚本退出场景

| 输出关键字 | 原因 | Agent 应做 |
|-----------|------|-----------|
| `swagger json file has not changed` | MD5 未变 | 告知用户 Swagger 无变更，已跳过生成 |
| `New model names detected (need confirmation)` | 新增 definition | 见下方「新模型映射确认交互」详细流程 |
| `new model mappings need confirmation` | 同上（main.py 提示） | 同上 |
| `Code generation failed` | 生成异常 | 展示错误堆栈，建议用户检查 Swagger 格式 |

### 首次生成 vs 增量生成

- **首次生成**：`--modelNameMap` 不传，脚本自动导出完整映射，正常生成代码
- **增量生成**：已有 `model_name_mapping.json` 时自动加载，新增模型会中断要求确认；无新增则直接生成
- **仅导出映射**：`--exportMappingOnly true`，不生成代码，用户审核映射后再跑增量

### 重新生成（Swagger 接口变更后）

1. 优先查找 `api_gen/generate.sh` 或 `command_history.log`，复用之前的 `--salt` 和 `--outputDir`
2. 直接重跑相同命令，脚本自动检测 Swagger 变更并输出 diff
3. 无需重新询问参数，除非用户明确要修改

### 新模型映射确认交互

当脚本输出 `New model names detected (need confirmation)` 时：

1. 将新增映射列表展示给用户（格式：`{原始名} → {混淆名}`）
2. 询问是否确认，或需要修改某些映射名
3. **用户确认** → 直接重跑相同命令（映射已自动导出到 `model_name_mapping.json`）
4. **用户需修改** → 等用户编辑完 `model_name_mapping.json` 后再重跑

## 生成代码特征

- `suspend fun` + Retrofit2 注解（`@Get/@Post/@Multipart`）
- `@Serializable data class` + `@SerialName` 字段
- 每字段上方 `// 原始名 中文描述` 注释
- 每模型类 KDoc 含原始名和使用它的接口列表
- 每 API 方法 KDoc 含描述 + HTTP 路径 + 所有响应码
- 文件上传生成 `@Part okhttp3.MultipartBody.Part`

## 注意事项

- **salt 一旦确定不可更换**，否则所有混淆名变化，现有引用全部失效。注意脚本会自动在 salt 前拼接 `swagger-kotlin-codegen-salt-` 前缀再参与哈希计算
- `model_name_mapping.json` 和 `generate.sh` 应纳入版本控制
- 需要 Python 3.10+，无需 pip install，直接运行脚本即可
