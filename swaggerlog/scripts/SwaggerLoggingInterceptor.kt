package com.cdahmad.swaggerlog

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonPrimitive
import com.google.gson.annotations.SerializedName
import com.google.gson.stream.JsonReader
import com.google.gson.stream.JsonToken
import com.google.gson.stream.JsonWriter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.FormBody
import okhttp3.Interceptor
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okio.Buffer
import java.io.File
import java.io.StringReader
import java.io.StringWriter
import java.net.URI
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.time.Duration.Companion.hours

/** 日志级别 */
enum class LogLevel { INFO, WARN }

/**
 * 自定义 OkHttp 日志拦截器，支持 Swagger 文档驱动的 JSON 反混淆与格式化输出。
 *
 * @param baseUrl 基础 URL
 * @param swaggerDocUrl Swagger v2/api-docs 地址
 * @param deobfus 是否反混淆 JSON 字段名
 * @param filter 是否过滤未映射字段
 * @param format 是否格式化 JSON 输出
 * @param tagPrefix 日志 tag 前缀，默认 "SwaggerLog"。多模块时传入不同前缀以区分日志来源
 * @param cacheFile 缓存目录工厂
 * @param log 日志输出: (level: LogLevel, tag: String, msg: String) -> Unit
 */
class SwaggerLoggingInterceptor @JvmOverloads constructor(
    val baseUrl: String,
    val swaggerDocUrl: String,
    val deobfus: Boolean,
    val filter: Boolean,
    val format: Boolean = false,
    val tagPrefix: String = "SwaggerLog",
    val cacheFile: () -> File?,
    val log: (LogLevel, String, String) -> Unit,
) : Interceptor {

    companion object {
        private val UTF8 = StandardCharsets.UTF_8
        private const val LOG_MAX_LENGTH = 3000
        private const val MAX_RESPONSE_BODY_SIZE = 1_000_000
        private var id = AtomicInteger(0)
    }

    private var swaggerDocCache: SwaggerDocCache? = null

    private fun getSwaggerDocCache(): SwaggerDocCache? {
        if (swaggerDocCache != null) return swaggerDocCache
        swaggerDocCache = SwaggerDocCache(cacheFile, log, swaggerDocUrl, tagPrefix = tagPrefix).also {
            it.ensureFresh()
        }
        return swaggerDocCache
    }

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val startTime = System.currentTimeMillis()
        val currentId = id.getAndIncrement()
        val requestId = String.format(Locale.US, "%06d", currentId)
        val currentTag = "${tagPrefix}_$requestId"

        // Swagger 摘要（缓存损坏时降级，不影响请求日志）
        var swaggerSummary: String? = null
        var swaggerDoc: SwaggerDoc? = null
        try {
            getSwaggerDocCache()?.ensureFresh()
            swaggerDoc = getSwaggerDocCache()?.getCachedDoc()
            val swaggerPath = request.url.encodedPath
            val swaggerMethod = request.method.lowercase()
            swaggerSummary = swaggerDoc?.paths?.get(swaggerPath)?.get(swaggerMethod)?.richSummary(baseUrl)
        } catch (e: Exception) {
            // 缓存损坏时降级，不阻断日志输出
            log(LogLevel.WARN, currentTag, "Swagger doc unavailable: ${e.message}")
        }

        // 读取请求体
        var requestBodySummary = ""
        try {
            request.body?.let { body ->
                val contentType = body.contentType()
                val mediaType = contentType?.toString()?.lowercase() ?: ""
                if (mediaType.startsWith("application/json")) {
                    val buffer = Buffer()
                    body.writeTo(buffer)
                    val charset = contentType?.charset(UTF8) ?: UTF8
                    requestBodySummary = buffer.readString(charset)
                } else {
                    when {
                        body is FormBody ->
                            requestBodySummary = "<Form Body: ${body.size} fields>"
                        body is MultipartBody ->
                            requestBodySummary = "<Multipart Body: ${body.parts.size} parts>"
                        mediaType.startsWith("text/") ->
                            requestBodySummary = "<Text Body: $mediaType>"
                        else ->
                            requestBodySummary = "<Binary/Stream Body: $mediaType>"
                    }
                }
            }
        } catch (e: Exception) {
            log(LogLevel.WARN, currentTag, "-> Failed to inspect request body: ${e.message}")
            requestBodySummary = "<Request body inspection failed>"
        }

        log(LogLevel.INFO, currentTag, "-> ${request.method} ${request.url}")

        val response = chain.proceed(request)
        val duration = System.currentTimeMillis() - startTime
        val msgList = mutableListOf<String>()

        try {
            val responseBody = response.body
            var bodyString = ""
            if (responseBody != null) {
                try {
                    val source = responseBody.source()
                    source.request(Long.MAX_VALUE)
                    val buffer = source.buffer
                    val charset = responseBody.contentType()?.charset(UTF8) ?: UTF8
                    if (buffer.size > MAX_RESPONSE_BODY_SIZE) {
                        bodyString = "<Response body too large (${buffer.size} bytes)>"
                    } else {
                        bodyString = buffer.clone().readString(charset)
                    }
                } catch (e: Exception) {
                    log(LogLevel.WARN, currentTag, "<- Failed to read response body: ${e.message}")
                }
            }

            msgList.add("<- ${request.method} ${request.url} ${response.code} ($duration ms) ${response.message}")
            msgList.add("<- Swagger: $swaggerSummary")

            // 请求头
            val jsonObject = JsonObject()
            request.headers.forEach {
                if (it.second.isNotEmpty()) {
                    jsonObject.add(it.first, JsonPrimitive(it.second))
                }
            }
            msgList.add("-> Request Header:")
            msgList.add(jsonObject.toString())

            // 请求体
            if (requestBodySummary.startsWith("<")) {
                msgList.add("-> Request Body: $requestBodySummary")
            } else if (requestBodySummary.isEmpty()) {
                msgList.add("-> Request Body: null")
            } else {
                msgList.add("-> Request Body:")
                msgList.add(requestBodySummary)
                if (deobfus) {
                    swaggerDoc?.tripeDesc()?.takeIf { it.isNotEmpty() }?.let {
                        val deobfuscatedJson =
                            ObfuscateHelper.deobfuscateJson(requestBodySummary, it, format, filter)
                        msgList.add("-> Request Body: (Deobfuscated):")
                        if (format) {
                            deobfuscatedJson.jsonFormatString().forEach { msgList.add(it) }
                        } else {
                            msgList.add(deobfuscatedJson)
                        }
                    }
                }
            }

            // 响应体
            if (bodyString.isNotEmpty()) {
                msgList.add("<- Response Body:")
                msgList.add(bodyString)
                if (deobfus) {
                    swaggerDoc?.tripeDesc()?.takeIf { it.isNotEmpty() }?.let {
                        val deobfuscatedJson =
                            ObfuscateHelper.deobfuscateJson(bodyString, it, format, filter)
                        msgList.add("<- Response Body (Deobfuscated):")
                        if (format) {
                            deobfuscatedJson.jsonFormatString().forEach { msgList.add(it) }
                        } else {
                            msgList.add(deobfuscatedJson)
                        }
                    }
                }
            }

            msgList.forEach { printLongLog(it, currentTag) }
        } catch (e: Exception) {
            log(LogLevel.WARN, currentTag, "<- Error reading response body: ${e.message}")
        }

        return response
    }

    private fun String.jsonFormatString(): List<String> {
        val msgList = mutableListOf<String>()
        val lines = split("\n")
        var currentChunk = StringBuilder()
        for (line in lines) {
            if (currentChunk.length + line.length + 1 > LOG_MAX_LENGTH) {
                if (currentChunk.isNotEmpty()) {
                    msgList.add(currentChunk.toString())
                    currentChunk.clear()
                }
                if (line.length > LOG_MAX_LENGTH) {
                    line.chunked(LOG_MAX_LENGTH).forEach { part -> msgList.add(part) }
                    continue
                }
            }
            currentChunk.append(line).append("\n")
        }
        if (currentChunk.isNotEmpty()) {
            msgList.add(currentChunk.toString())
        }
        return msgList
    }

    private fun printLongLog(msg: String, tag: String) {
        if (msg.length <= LOG_MAX_LENGTH) {
            log(LogLevel.INFO, tag, msg)
        } else {
            msg.chunked(LOG_MAX_LENGTH).forEachIndexed { _, chunk ->
                log(LogLevel.INFO, tag, chunk)
            }
        }
    }
}

// ============================================================
// Swagger 文档缓存管理器（内存 + 文件 + TTL + 后台刷新）
// ============================================================
private class SwaggerDocCache(
    val cacheFile: () -> File?,
    val log: (LogLevel, String, String) -> Unit,
    val swaggerDocUrl: String,
    val ttlHours: Int = 24,
    val tagPrefix: String = "SwaggerLog",
) {
    val tag = "${tagPrefix}_SwaggerDocCache"
    private val CACHE_FILE_NAME = "swagger_v2_api_docs.json"
    private val TTL_MILLIS = ttlHours.hours.inWholeMilliseconds

    @Volatile
    private var memoryCache: Pair<SwaggerDoc, Long>? = null

    private val gson = Gson()
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val isRefreshing = AtomicBoolean(false)

    private fun getCacheFile(): File? = cacheFile()?.let { File(it, CACHE_FILE_NAME) }

    fun ensureFresh() {
        val now = System.currentTimeMillis()
        val cached = getFromMemoryOrDisk()
        if (cached == null) {
            refreshInBackground(force = false)
            return
        }
        val (doc, savedAt) = cached
        memoryCache = doc to savedAt
        if (now - savedAt > TTL_MILLIS) {
            refreshInBackground(force = true)
        }
    }

    fun getCachedDoc(): SwaggerDoc? = memoryCache?.first ?: readFromFile()?.first

    private fun getFromMemoryOrDisk(): Pair<SwaggerDoc, Long>? =
        memoryCache ?: readFromFile()

    private fun readFromFile(): Pair<SwaggerDoc, Long>? {
        return try {
            val cacheFile = getCacheFile() ?: return null
            if (!cacheFile.exists()) return null
            val json = cacheFile.readText(Charsets.UTF_8)
            if (json.isBlank()) {
                cacheFile.delete()
                return null
            }
            val wrapper = gson.fromJson(json, SwaggerCacheWrapper::class.java)
            // 校验缓存完整性：timestamp 有效、swaggerDoc 非空、paths 非空
            if (wrapper.timestamp <= 0 ||
                wrapper.swaggerDoc == null ||
                wrapper.swaggerDoc?.paths == null
            ) {
                log(LogLevel.WARN, tag, "Invalid cache content, deleting")
                cacheFile.delete()
                return null
            }
            wrapper.swaggerDoc to wrapper.timestamp
        } catch (e: Exception) {
            log(LogLevel.WARN, tag, "Failed to parse cache file: ${e.message}, deleting it")
            try {
                getCacheFile()?.delete()
            } catch (_: Exception) {
                // 删除失败忽略
            }
            null
        }
    }

    private fun refreshInBackground(force: Boolean = false) {
        if (!force && isRefreshing.getAndSet(true)) return
        scope.launch {
            var response: Response? = null
            var newDoc: SwaggerDoc? = null
            try {
                log(LogLevel.INFO, tag, "Refreshing Swagger doc from network")
                val client = OkHttpClient.Builder()
                    .connectTimeout(30, TimeUnit.SECONDS)
                    .readTimeout(60, TimeUnit.SECONDS)
                    .build()
                val request = Request.Builder().url(swaggerDocUrl).build()
                log(LogLevel.INFO, tag, "Request URL: ${request.url}")
                response = client.newCall(request).execute()
                if (response.isSuccessful) {
                    val bodyString = response.body?.string()
                    if (bodyString.isNullOrBlank()) {
                        log(LogLevel.WARN, tag, "Received empty or blank response body")
                    } else {
                        newDoc = gson.fromJson(bodyString, SwaggerDoc::class.java)
                        // 校验解析结果完整性：paths 必须非空，否则视为无效
                        if (newDoc != null && newDoc?.paths != null) {
                            val now = System.currentTimeMillis()
                            memoryCache = newDoc to now
                            cacheFile()?.let { ctx ->
                                val wrapper = SwaggerCacheWrapper(
                                    timestamp = now,
                                    swaggerDoc = newDoc,
                                )
                                val tempFile = File(ctx, "${CACHE_FILE_NAME}.tmp")
                                try {
                                    tempFile.writeText(gson.toJson(wrapper), Charsets.UTF_8)
                                    if (tempFile.renameTo(File(ctx, CACHE_FILE_NAME))) {
                                        log(LogLevel.INFO, tag, "Successfully refreshed and cached Swagger doc to disk")
                                    } else {
                                        log(LogLevel.WARN, tag, "Failed to rename temp cache file")
                                        tempFile.delete()
                                    }
                                } catch (e: Exception) {
                                    log(LogLevel.WARN, tag, "Failed to write cache file: ${e.message}")
                                    tempFile.delete()
                                }
                            }
                        } else {
                            log(LogLevel.WARN, tag, "Parsed SwaggerDoc is null or has null paths, discarding")
                        }
                    }
                } else {
                    log(LogLevel.WARN, tag, "HTTP request failed: ${response.code} ${response.message}")
                }
            } catch (e: Exception) {
                log(LogLevel.WARN, tag, "Exception during Swagger doc refresh: ${e.message}")
            } finally {
                isRefreshing.set(false)
                response?.close()
            }
        }
    }

    private data class SwaggerCacheWrapper(
        @SerializedName("timestamp") val timestamp: Long,
        @SerializedName("swaggerDoc") val swaggerDoc: SwaggerDoc,
    )
}

// ============================================================
// Swagger 文档数据模型
// ============================================================

data class SwaggerDoc(
    @SerializedName("swagger") val swagger: String,
    @SerializedName("paths") val paths: Map<String, Map<String, Operation>>,
    @SerializedName("definitions") val definitions: Map<String, Definition>? = null,
) {
    private var descTripeMap: MutableMap<String, Pair<String, String>>? = null

    /**
     * 从 Swagger definitions 中提取字段的原始名 → (原始名, 描述) 映射。
     * 用于反混淆时还原被混淆的 JSON key。
     */
    fun tripeDesc(): Map<String, Pair<String, String>> {
        if (descTripeMap == null) {
            val map = mutableMapOf<String, Pair<String, String>>()
            definitions?.forEach { (_, modelSchema) ->
                modelSchema.properties?.forEach { (propName, propSchema) ->
                    val originKey = propSchema.desc()
                    if (originKey != null) {
                        if (propName !in listOf("code", "msg", "data")) {
                            map[propName] = originKey to (propSchema.description ?: "")
                        }
                    }
                }
            }
            descTripeMap = map
        }
        return descTripeMap ?: emptyMap()
    }

    data class Definition(
        @SerializedName("type") val type: String,
        @SerializedName("properties") val properties: Map<String, Property>? = null,
    ) {
        data class Property(
            @SerializedName("type") val type: String?,
            @SerializedName("description") val description: String?,
        ) {
            /** 取 description 冒号前的部分作为原始字段名 */
            fun desc(): String? = description?.split(":")?.get(0)?.trim()
        }
    }

    data class Operation(
        @SerializedName("tags") val tags: List<String>,
        @SerializedName("summary") val summary: String,
        @SerializedName("description") val description: String,
        @SerializedName("operationId") val operationId: String,
        @SerializedName("consumes") val consumes: List<String>,
        @SerializedName("produces") val produces: List<String>,
        @SerializedName("parameters") val parameters: List<Map<String, Any?>>? = null,
        @SerializedName("deprecated") val deprecated: Boolean,
    ) {
        fun richSummary(baseUrl: String): String {
            val paths = tags.joinToString("/")
            val url = "${baseUrl}doc.html#/default/$paths/$operationId"
            val uri = URI(url)
            return "$summary ${uri.toASCIIString()}"
        }
    }
}

// ============================================================
// JSON 反混淆工具
// ============================================================

private object ObfuscateHelper {

    private val WHITELISTED_KEYS = setOf("data", "code", "msg")

    /**
     * 反混淆 JSON 字段名并可选过滤未映射字段。
     *
     * @param obfuscatedJson 混淆后的 JSON
     * @param keyMapping 混淆字段名 → (原始字段名, 描述)
     * @param format 是否 pretty-print
     * @param filter true=仅保留白名单+mapping 中存在的字段; false=保留全部仅反混淆
     */
    fun deobfuscateJson(
        obfuscatedJson: String,
        keyMapping: Map<String, Pair<String, String>>,
        format: Boolean,
        filter: Boolean,
    ): String {
        val reader = JsonReader(StringReader(obfuscatedJson))
        val writer = StringWriter()
        val jsonWriter = JsonWriter(writer).apply { serializeNulls = true }
        try {
            process(reader, jsonWriter, keyMapping, filter)
        } finally {
            reader.close()
            jsonWriter.close()
        }
        val rawResult = writer.toString()
        return if (format) {
            try {
                val gson = Gson()
                val prettyGson = GsonBuilder().setPrettyPrinting().create()
                val element: JsonElement = gson.fromJson(rawResult, JsonElement::class.java)
                prettyGson.toJson(element)
            } catch (_: Exception) {
                // pretty-print 失败时降级返回原始结果，不阻断日志输出
                rawResult
            }
        } else {
            rawResult
        }
    }

    private fun process(
        reader: JsonReader,
        writer: JsonWriter,
        mapping: Map<String, Pair<String, String>>,
        filter: Boolean,
    ) {
        when (reader.peek()) {
            JsonToken.BEGIN_OBJECT -> {
                reader.beginObject()
                writer.beginObject()
                while (reader.hasNext()) {
                    val obfuscatedName = reader.nextName()
                    val originalName = mapping[obfuscatedName]?.first ?: obfuscatedName
                    if (filter) {
                        val isInWhitelist = originalName in WHITELISTED_KEYS
                        val isInMapping = mapping.containsKey(obfuscatedName)
                        if (!isInWhitelist && !isInMapping) {
                            reader.skipValue()
                            continue
                        }
                    }
                    writer.name(originalName)
                    process(reader, writer, mapping, filter)
                }
                reader.endObject()
                writer.endObject()
            }
            JsonToken.BEGIN_ARRAY -> {
                reader.beginArray()
                writer.beginArray()
                while (reader.hasNext()) {
                    process(reader, writer, mapping, filter)
                }
                reader.endArray()
                writer.endArray()
            }
            JsonToken.STRING -> writer.value(reader.nextString())
            JsonToken.NUMBER -> {
                val numStr = reader.nextString()
                writer.value(numStr)
            }
            JsonToken.BOOLEAN -> writer.value(reader.nextBoolean())
            JsonToken.NULL -> {
                reader.nextNull()
                writer.nullValue()
            }
            else -> reader.skipValue()
        }
    }
}
