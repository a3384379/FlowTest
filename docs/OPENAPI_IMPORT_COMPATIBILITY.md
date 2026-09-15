# Swagger / OpenAPI 导入兼容性

## 处理边界

文件和 URL 获取到 JSON/YAML 后共用以下链路：

```text
Source → JSON/YAML 解析及资源检查 → Dialect Detection
       → OperationAdapter → SourceNormalizer
       → Canonical Contract → Strict Canonical Validator → Import Diff
```

`swagger: "2.0"` 使用 SWAGGER_2_0；OpenAPI 3.0 与 3.1 在诊断中分别标记
OPENAPI_3_0、OPENAPI_3_1。持久化 source_type 仍是 swagger2/openapi3，不需要迁移。
Swagger UI、Springdoc、FastAPI 页面 discovery 获取原始文档后走相同解析器。
Knife4j/Springfox 的 raw spec 可导入；页面发现依赖可识别的配置 URL 或约定路径，
不执行页面 JavaScript，不保证所有定制页面均可发现。

## 支持矩阵

FULL 表示表内限定能力可完整表达；PARTIAL 表示只表达子集；WARNING 表示可导入但需要查看诊断；
UNSUPPORTED 表示未实现。下表不表示完整实现整个规范。

| 能力 | Swagger 2.0 | OpenAPI 3.0.x | OpenAPI 3.1.x |
| --- | --- | --- | --- |
| JSON / YAML | FULL | FULL | FULL |
| Schema | PARTIAL | PARTIAL | PARTIAL |
| RequestBody | PARTIAL | PARTIAL | PARTIAL |
| Form | FULL（普通字段） | PARTIAL（不处理 encoding） | PARTIAL（不处理 encoding） |
| Multipart | FULL（文本与单文件字段） | PARTIAL（binary，无 encoding） | PARTIAL（binary，无 encoding） |
| File | FULL（file → string/binary） | FULL（string/binary） | FULL（string/binary） |
| Query array | PARTIAL | PARTIAL | PARTIAL |
| Security | PARTIAL | PARTIAL | PARTIAL |
| Server/basePath | PARTIAL | PARTIAL | PARTIAL |
| 内部 $ref | PARTIAL | PARTIAL | PARTIAL |
| 远程 $ref | WARNING（不拉取） | WARNING（不拉取） | WARNING（不拉取） |
| Composition | PARTIAL | PARTIAL | PARTIAL |
| Nullable | UNSUPPORTED（非标准） | FULL（nullable 注解） | FULL（type union） |
| JSON Schema 2020-12 | UNSUPPORTED | UNSUPPORTED | PARTIAL |
| Vendor Extensions | WARNING | WARNING | WARNING |

### Swagger 2.0

- 支持 definitions、中文及含 `« »` 的 definition 名、内部 JSON Pointer 转义。
- body 参数进入 request_body；所有 formData 字段组成 object，required 保留为字段列表。
- file 转换为 string/binary，包括响应 Schema；不将文件内容或路径导入为真实上传文件。
- consumes 优先 operation，其次 document。未指定时按 body / 普通表单 / 文件选择
  application/json / application/x-www-form-urlencoded / multipart/form-data，并产生诊断。
- produces 用于响应媒体类型；多媒体表示只选择一个 Canonical 表示。
- 支持 basic、apiKey；其他认证模式和多个 security requirement 仅保留既有第一项行为，
  不声称支持 OAuth 授权流程或全部 AND/OR 组合。
- 支持 additionalProperties、enum、default、数值边界、pattern、items、readOnly、allOf。
  布尔 exclusiveMinimum/Maximum 转为数值边界；字符串 discriminator 转为 propertyName。
- collectionFormat：multi → form/explode=true；csv → form 或 simple；ssv → spaceDelimited；
  pipes → pipeDelimited；tsv → tabDelimited 兼容样式并 warning。
  query 数组示例/default 会生成重复 query key 或对应分隔符。只有占位变量时不自动展开运行时数组；
  Canonical style/explode 保留序列化语义。formData 数组的运行时展开尚未完整支持。

### OpenAPI 3.0

支持 components.schemas/parameters/requestBodies/responses 内部引用、JSON 和 +json 请求体、
multipart binary、URL 编码表单、nullable、oneOf/anyOf/allOf/not、discriminator、
additionalProperties、参数 style/explode、响应 Schema、文档级 servers 和变量默认值。
仅选择一个媒体类型，不支持 multipart encoding、响应 header 完整建模和所有服务器覆盖规则。
example/default 的存储继续服从现有请求级脱敏策略。

### OpenAPI 3.1

保留 type union、const、组合 Schema；内部引用可以指向 $defs。
布尔 Schema 转换为 `{}` 或 `{"not": {}}`。
3.1 Schema 的 $ref 同级约束作为 allOf 合取处理，不覆盖被引用的约束。

prefixItems、unevaluatedProperties、dependentSchemas、dependentRequired、if/then/else、
contains、minContains/maxContains、contentEncoding、contentMediaType 等当前不进入
Canonical 执行约束；记录源位置和关键词并标记 partial，不能据此声称完成 2020-12 校验。
$defs 作为引用容器解析，容器本身不写入 Canonical。自定义 dialect、动态引用、anchor、
外部 URI scope 和完整 vocabulary 尚未实现。

## 文本规范化和安全

Source 层将 title/description 的 CRLF、CR、LF、tab 及其他 C0/DEL 控制字符转换为空格。
记录 `SCHEMA_TEXT_WHITESPACE_NORMALIZED`，保持 type、required、enum 和 bounds 等语义。
Canonical Validator 继续拒绝带控制字符的文本、属性名、format 和 discriminator。
不改动现有脱敏配置，不新增日志，不将诊断字段原值复制到 value_preview（该字段为 null）。

资源预算：源文档 32 MiB、200000 个展开节点、96 层嵌套；包括 YAML 别名展开。
每个接口最多 10000 个 Schema 节点、500 条诊断；单 Schema 最多 500 个属性、50 个组合分支，
并继续通过 Canonical 的 512 KiB、枚举、正则等限制。Schema 展开在 22 层截断并 warning；
引用栈最多 24 层，循环引用明确记录截断。远程引用不发起网络请求，可从 source_path 回查原引用。

## 诊断和失败策略

- FATAL：不可解析、根节点非对象、未知文档格式、无 HTTP Operation、无法继续处理的资源超限。
  通过现有 IMPORT_INVALID 标准错误 envelope 返回，保留 trace ID。
- WARNING：可安全规范化的文本、缺失/循环/远程引用、不支持的关键词、路径参数不匹配、GET body。
  部分约束不能表达时保留其他约束并标记 partial；单接口结构校验失败时生成仅含方法和路径的 partial 契约。
- INFO：诊断类型预留，不影响导入。当前适配行为使用 WARNING，避免掩盖兼容性变化。

Diff 的每个结果新增 diagnostics，包含 source_version、source_dialect、method、endpoint、
operation_id、source_path、canonical_path、keyword、value_preview、severity、code、message、
normalized_as、suggested_fix。前端显示警告数量并可展开 JSON 详情。
未知 x-* 字段不写入 Canonical；源文档中保留原值，通过诊断位置回查。
源资源和无法表达的语义不混入 Canonical Schema，避免放宽内部允许列表。

Swagger 1.x 明确提示：

> Legacy Swagger 1.x is not currently supported; please convert to Swagger 2.0 or OpenAPI 3.x.

## 持久化、fingerprint 和 Diff

无需数据库迁移或 Canonical 版本变化；诊断存入现有 ImportRun.results JSON，旧结果默认 diagnostics=[]。
诊断不进入 ImportedOperation.content_fingerprint，import_key 仍由 method/path 生成。
规范化前后语义确有变化的接口（新增 formData Schema、collectionFormat、展开引用、partial 状态）
可能在首次重新导入时显示 changed；重复导入相同文档结果稳定。普通已有无兼容变化的接口保持原表示。

## 回归验证

`backend/tests/fixtures/importers/swagger2-compatibility.yaml` 是匿名最小 fixture，
精确覆盖两个真实故障 definition 的多行 description，以及上传、三个 multi 接口、path mismatch、GET body。
`test_openapi_compatibility.py` 覆盖三个版本、引用、组合、表单、安全边界和稳定性；
`test_imports_api.py` 验证 partial 导入诊断能通过实际 API 返回。
现有 Postman/HAR/cURL/Bruno 解析测试继续执行。

规范依据：[Swagger 2.0](https://spec.openapis.org/oas/v2.0.html)、
[OpenAPI 3.1.0](https://spec.openapis.org/oas/v3.1.0.html)。
