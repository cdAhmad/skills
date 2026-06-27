# Skills

Android 开发辅助 Skill 集合。

## Skills

### figma-image

从 Figma 设计稿下载 4x PNG 并生成 Android 各密度 WebP mipmap。

- 支持 Figma URL 自动下载、本地 PNG、本地文件夹批量处理
- 生成 mdpi / hdpi / xhdpi / xxhdpi / xxxhdpi 五档密度
- 默认输出到当前 Android 项目 `app/src/main/res/mipmap-*/`
- 处理完成后自动清理源文件缓存

### swaggerlog

项目 SwaggerLoggingInterceptor 使用方式。

- 查看/理解项目中的网络日志拦截器用法
- 在现有 flavor 体系中为新模块添加 SwaggerLog 日志
- 调整拦截器参数（deobfus/filter/format 等）
- 排查 Swagger 缓存或反混淆问题
- 处理 Swagger v2 api-docs 字段映射规则

### swagger-interface-migration

Swagger 接口/字段名迁移工具。从 Swagger JSON description 提取替换规则，批量迁移代码库。

- 支持本地 JSON 文件或网络 URL（自动补全 `/v2/api-docs`）
- 预览模式（`--dry-run`）安全审查后再执行
- 词边界匹配避免误替换子字符串

### apiGen

Swagger/OpenAPI → Kotlin 代码生成器。纯 Python，零依赖。

- 生成 `suspend fun` + Retrofit2 + kotlinx.serialization 代码
- MD5 去重、增量更新、自动备份旧代码
- 模型名映射保持稳定，支持审核确认

### swagger_annotate

基于 Swagger JSON 为混淆后的 Kotlin Bean 自动补充字段注释。

- 字段名自动匹配（Swagger property key ↔ Kotlin 字段名）
- 类级别 KDoc 生成（接口地址 / 参数说明）
- 手动映射兜底（MANUAL_COMMENTS 覆盖 Swagger 未定义的通用类）
- CI 检查模式（`--check-only` 有缺失注释时 exit 1）

## 使用

在 Android 项目根目录下，通过 Claude Code skill 调用：

```bash
# Figma 图片 → WebP
/figma-image

# SwaggerLog 配置
/swaggerlog

# Swagger 接口迁移
/swagger-interface-migration

# Swagger → Kotlin 代码生成
/apiGen

# Swagger Bean 注释补充
/swagger_annotate
```
