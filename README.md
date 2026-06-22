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

## 使用

在 Android 项目根目录下，通过 Claude Code skill 调用：

```bash
# Figma 图片 → WebP
/figma-image

# SwaggerLog 配置
/swaggerlog
```
