---
name: "swaggerlog"
version: "1.1.0"
description: "项目 SwaggerLoggingInterceptor 使用方式。触发场景：(1) 查看/理解项目中的网络日志拦截器用法，(2) 在现有 flavor 体系中为新模块添加 SwaggerLog 日志，(3) 调整拦截器参数（deobfus/filter/format 等），(4) 排查 Swagger 缓存或反混淆问题，(5) 处理 Swagger v2 api-docs 字段映射规则。"
---

# SwaggerLoggingInterceptor — 项目使用方式

## 是什么

`SwaggerLoggingInterceptor`（`com.cdahmad.swaggerlog`）是一个带 Swagger v2 `api-docs` 集成的 OkHttp 日志拦截器，**仅在 devTest / preProduct flavor 生效**（`noGoogle` sourceSet），google 生产包不包含。

核心能力：
- **自动拉取 + 缓存** Swagger 文档（内存 + 文件双层，24h TTL，后台刷新）
- **JSON 字段反混淆**：用 Swagger definitions 中 `description` 字段携带的 `原始名:描述` 映射，将混淆后的 JSON key 还原为可读原名
- **可选字段过滤**：只保留 Swagger 定义的字段 + 白名单（`data`/`code`/`msg`）
- **Pretty-print**：格式化 JSON 输出
- **大日志分段**：单条日志超 3000 字符自动 `chunked` 分段

---

## 项目中的集成模式（三步）

### 第一步：定义 facade 接口

`src/main/java/.../google/RaucidGoogleInterceptor.kt`：

```kotlin
interface RaucidGoogleInterceptor {
    /** 返回 OkHttp Interceptor，或 null 表示不注入 */
    fun getInterceptor(): Interceptor?
}
```

### 第二步：Source Set 二选一

利用 AGP flavor sourceSet 合并规则，`noGoogle/` 与 `google/` 各自提供同名同包的 `GoogleServiceImpl`，编译期二选一。

**`src/noGoogle/.../google/GoogleServiceImpl.kt`**（devTest / preProduct — 注入日志拦截器）：

```kotlin
internal class GoogleServiceImpl : ..., RaucidGoogleInterceptor {
    override fun getInterceptor(): Interceptor? {
        return SwaggerLoggingInterceptor(
            baseUrl = BuildConfig.BASE_URL + "/",
            swaggerDocUrl = "${BuildConfig.BASE_URL}/v2/api-docs",
            deobfus = true,
            filter = true,
            format = true,
            tagPrefix = "RaucidLog",
            cacheFile = { RaucidAppApplication.instance.cacheDir },
            log = { level, tag, msg ->
                when (level) {
                    LogLevel.INFO -> Log.d(tag, msg)
                    LogLevel.WARN -> Log.w(tag, msg)
                }
            }
        )
    }
}
```

**`src/google/.../google/GoogleServiceImpl.kt`**（生产包 — 不注入日志拦截器）：

```kotlin
internal class GoogleServiceImpl : ..., RaucidGoogleInterceptor {
    override fun getInterceptor(): Interceptor? = null
}
```

### 第三步：OkHttp 绑定

`src/main/.../data/remote/RaucidRetrofitClient.kt`：

```kotlin
val okHttpClient: OkHttpClient by lazy {
    OkHttpClient.Builder()
        .apply {
            addInterceptor(RaucidHeadInterceptor())             // ① 公共 Header
            RaucidGoogleServices.interceptor.getInterceptor()
                ?.let { addInterceptor(it) }                   // ② 日志（仅 noGoogle）
            addInterceptor(RaucidEncodeInterceptor())           // ③ AES 加密
            addInterceptor(RaucidDecodeInterceptor())           // ④ AES 解密
        }
        .connectTimeout(60, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()
}
```

> 日志拦截器位于加密层之上、公共 Header 之下 —— 打印的是明文请求/响应，方便调试。

---

## 源代码文件

拦截器源文件及配套配置位于 skill 的 `scripts/` 目录：

| 文件 | 用途 |
|------|------|
| `scripts/SwaggerLoggingInterceptor.kt` | 拦截器完整源码（546行），包名 `com.cdahmad.swaggerlog` |
| `scripts/proguard-rules.pro` | R8/ProGuard 混淆规则 |

### 依赖

源文件依赖以下库（需在 `build.gradle.kts` 中声明）：

```kotlin
dependencies {
    implementation("com.google.code.gson:gson:2.10.1")       // JSON 解析 + SwaggerDoc 模型
    implementation("com.squareup.okhttp3:okhttp:4.12.0")      // Interceptor + 文档拉取
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3") // 后台刷新
}
```

### 使用方式

将 `SwaggerLoggingInterceptor.kt` 复制到非生产 sourceSet（如 `src/noGoogle/java/com/cdahmad/swaggerlog/`），google flavor 编译时不会包含此文件，无需额外隔离。

通过构造函数直接实例化，所有参数在构造时传入、全链路不可变：

---

## R8 / ProGuard 配置

拦截器内部使用 Gson 反射解析 Swagger 文档缓存，R8 全模式混淆下数据模型会被重命名/移除，必须添加 keep 规则。

将 `scripts/proguard-rules.pro` 的内容追加到项目 `app/proguard-rules.pro`：

```
# SwaggerLog 内部数据模型（由 gson.fromJson() 反射构造，R8 无法自动追踪）
-keep class com.cdahmad.swaggerlog.SwaggerDoc { *; }
-keep class com.cdahmad.swaggerlog.SwaggerDoc$** { *; }
-keepclassmembers class com.cdahmad.swaggerlog.SwaggerDocCache$SwaggerCacheWrapper { *; }
```

> 不加这些规则时，`gson.fromJson(bodyString, SwaggerDoc::class.java)` 返回的 `SwaggerDoc.paths` 为 null，反混淆功能静默失效（日志仍正常输出，只是无反混淆）。

---

## 构造函数参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `baseUrl` | `String` | API 基础 URL（用于 Swagger 摘要链接拼接） |
| `swaggerDocUrl` | `String` | Swagger v2 `api-docs` JSON 地址（如 `{baseUrl}/v2/api-docs`） |
| `deobfus` | `Boolean` | 是否反混淆 JSON 字段名（用 Swagger description 映射还原） |
| `filter` | `Boolean` | 是否过滤未在 Swagger 定义的字段（仅保留白名单 + mapping 中的 key） |
| `format` | `Boolean` | 是否 pretty-print JSON（默认 `false`） |
| `tagPrefix` | `String` | 日志 tag 前缀，默认 `"SwaggerLog"`。多模块时传入不同前缀以区分日志来源 |
| `cacheFile` | `() -> File?` | 缓存目录工厂（lambda，延迟求值避免初始化时序问题） |
| `log` | `(level: LogLevel, tag: String, msg: String) -> Unit` | 日志输出回调，`level` 为 `LogLevel.INFO` / `LogLevel.WARN` 枚举，`tag` 为当前请求 tag，`msg` 为日志内容 |

---

## Swagger 字段映射约定

`SwaggerLoggingInterceptor` 依赖 Swagger definitions 中 `description` 字段的特定格式来反混淆 JSON key：

```json
{
  "definitions": {
    "SomeModel": {
      "properties": {
        "a": { "type": "string", "description": "userName:用户姓名" },
        "b": { "type": "integer", "description": "userAge:用户年龄" }
      }
    }
  }
}
```

- `description` 冒号前的部分（`userName`）为**原始字段名**
- 冒号后的部分为中文说明（仅用于可读性，不参与反混淆逻辑）
- 反混淆时 `"a"` → `"userName"`，`"b"` → `"userAge"`
- 白名单 key（`data`/`code`/`msg`）即使不在 mapping 中也保留（`filter=true` 时）

---

## 缓存策略

`SwaggerDocCache` 内部实现双层缓存：

| 层级 | 存储 | TTL | 行为 |
|------|------|-----|------|
| 内存 | `@Volatile var memoryCache` | 24h | 进程内存，最快 |
| 文件 | `cacheDir/swagger_v2_api_docs.json` | 24h | 跨进程重启持久化 |

- `ensureFresh()` 检查 TTL，过期后在后台协程（`Dispatchers.IO`）异步刷新
- 缓存损坏（空内容、解析失败、paths 为 null）自动删除并重新拉取
- 网络请求失败时降级使用过期缓存；缓存完全不可用时跳过反混淆但正常输出日志

---

## 拦截器链位置（项目实际）

```
请求 → 公共Header → SwaggerLog(明文) → AES加密 → 网络
响应 → 网络 → AES解密 → SwaggerLog(明文) → 公共Header → 业务层
```

- SwaggerLog 在加密**外侧**（先解密再打日志，先打日志再加密）
- 打印的是人类可读的明文 JSON，已反混淆 + 格式化
- 生产包（google flavor）不注入此拦截器，零性能开销

---

## 关键陷阱

### 1. cacheFile 必须用 lambda 延迟求值

```kotlin
// ❌ 错误：初始化时 Application 可能尚未就绪
cacheFile = Application.instance.cacheDir

// ✅ 正确：lambda 延迟到首次 intercept 时才求值
cacheFile = { Application.instance.cacheDir }
```

### 2. 大响应体保护

响应体超过 **1MB** 时跳过内容读取，日志输出 `<Response body too large (N bytes)>`，避免 OOM。

### 3. 请求体只处理 JSON

非 JSON 请求体（FormBody、MultipartBody、Binary）仅输出摘要（字段数/part 数/类型），不做反混淆。

### 4. 缓存损坏不阻断请求

Swagger 文档拉取失败或缓存损坏时，拦截器**降级**继续输出原始日志（无反混淆），不抛异常阻断请求链。

### 5. Swagger URL 格式

拦截器内部假定 Swagger v2 格式：`{baseUrl}/v2/api-docs`。如果后端是 Swagger v3（OpenAPI 3.0），需将 URL 改为 `{baseUrl}/v3/api-docs` 并相应调整 `SwaggerDoc` 数据模型。

### 6. 日志 tag 格式

每条请求独立 tag：`SwaggerLog_000001`、`SwaggerLog_000002`... 配合 `pidcat` 或 Android Studio Logcat filter 可精确定位单次请求。

多模块时通过 `tagPrefix` 参数传入不同前缀区分来源，如 `tagPrefix = "OrderModule"` → tag 输出 `OrderModule_000001`。

---

## 常见问题排查

| 现象 | 可能原因 | 排查步骤 |
|------|----------|----------|
| 日志有输出但无反混淆 | Swagger 缓存未拉取或损坏 | 清除缓存：`adb shell run-as <pkg> rm -f cache/swagger_v2_api_docs.json`，重启 App 触发重新拉取 |
| 日志有输出但无反混淆（Release 包） | R8 混淆导致 `SwaggerDoc` 反序列化失败 | 检查 `proguard-rules.pro` 是否包含 SwaggerLog keep 规则 |
| `Swagger Doc URL 请求失败` | 后台未暴露 `/v2/api-docs` 端点 | `curl {BASE_URL}/v2/api-docs` 确认可访问 |
| `Parsed SwaggerDoc null paths` | Swagger JSON 格式不匹配（v3 vs v2） | 检查返回 JSON 顶层是否有 `swagger`/`paths`/`definitions` 字段 |
| 反混淆后字段名不对 | `description` 格式不符合 `原始名:说明` 约定 | 检查后端 Swagger definitions 中的 description 是否包含冒号分隔的原始字段名 |
| Release 包出现 `ClassNotFoundException: SwaggerDoc` | 源文件放错 sourceSet，Release 包也编译进去了 | 确认 `SwaggerLoggingInterceptor.kt` 在 `noGoogle/` 下，不在 `main/` 下 |

---

## 不适用场景

- Release 包需要网络日志 → 不应使用 Source Set 隔离，考虑用 `BuildConfig.ENABLE_LOG` 运行时开关
- 后端不是 Swagger/OpenAPI → 反混淆能力不可用，改用标准 `HttpLoggingInterceptor`
- 响应体超大（>1MB 常态化）→ 当前直接跳过，需自行修改 `LOG_MAX_LENGTH` 和大小阈值
- KMP 项目 → SwaggerDocCache 内部用 `OkHttpClient` 同步请求，不适用于 `ktor` 等非 OkHttp 栈

---

## 备忘：相关命令

```bash
# 查看 devDebug 日志（SwaggerLoggingInterceptor 生效）
./gradlew :app:assembleDevDebug
adb logcat -s SwaggerLog_*:D

# 确认 release 包不含 SwaggerLog 符号
./gradlew :app:assembleGoogleRelease
unzip -l app/build/outputs/apk/google/release/*.apk | grep SwaggerLog
# 预期：无输出

# 手动清除 Swagger 缓存
adb shell run-as <pkg> rm -f cache/swagger_v2_api_docs.json
```
