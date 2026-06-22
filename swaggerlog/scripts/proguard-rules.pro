# ============================================================
# SwaggerLog R8/ProGuard 规则
# ============================================================
# SwaggerLog 使用 Gson 反射解析 Swagger v2 api-docs JSON，
# 内部数据模型（SwaggerDoc / SwaggerDocCache$SwaggerCacheWrapper）
# 在 R8 全模式混淆下会被重命名/移除，导致 gson.fromJson() 返回 null。
# 以下规则确保这些类不被混淆或移除。

# SwaggerDoc 及内部类（Definition / Property / Operation 等）
-keep class com.cdahmad.swaggerlog.SwaggerDoc { *; }
-keep class com.cdahmad.swaggerlog.SwaggerDoc$** { *; }

# SwaggerDocCache 内部缓存包装类（文件缓存序列化用）
-keepclassmembers class com.cdahmad.swaggerlog.SwaggerDocCache$SwaggerCacheWrapper { *; }

# OkHttp（SwaggerDocCache 内部用独立 OkHttpClient 拉取文档）
-dontwarn okhttp3.**
-dontwarn okio.**
