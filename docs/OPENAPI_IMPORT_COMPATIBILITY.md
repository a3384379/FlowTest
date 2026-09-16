# Swagger / OpenAPI 导入兼容性

## 处理边界

文件和 URL 获取到 JSON/YAML 后共用以下链路：

```text
Source → JSON/YAML 解析及资源检查 → Dialect Detection
       → OperationAdapter → SourceNormalizer
       → Canonical Contract → Strict Canonical Validator → Import Diff
```

`swagger: "2.0"` 使用 SWAGGER_2_0；OpenAPI 3.0、3.1、3.2 在诊断中分别标记
OPENAPI_3_0、OPENAPI_3_1、OPENAPI_3_2。持久化 source_type 仍是 swagger2/openapi3，不需要迁移。
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
- 支持 basic、apiKey；其他认证模式和 AND/OR 组合标记 partial，要求人工配置。
  未配置认证时阻止默认执行，不声称支持 OAuth 授权流程。
- 支持 additionalProperties、enum、default、数值边界、pattern、items、readOnly、allOf。
  布尔 exclusiveMinimum/Maximum 转为数值边界；字符串 discriminator 转为 propertyName。
- collectionFormat：multi → form/explode=true；csv → form 或 simple；ssv → spaceDelimited；
  pipes → pipeDelimited；tsv → tabDelimited 兼容样式并 warning。
  query 数组示例/default 会生成重复 query key 或对应分隔符。占位变量可以绑定 JSON 标量数组字符串，
  执行时按 Canonical style/explode 展开。复杂对象数组和 formData 数组需要人工配置。

### OpenAPI 3.0

支持 components.schemas/parameters/requestBodies/responses 内部引用、JSON 和 +json 请求体、
multipart binary、URL 编码表单、nullable、oneOf/anyOf/allOf/not、discriminator、
additionalProperties、参数 style/explode、响应 Schema、operation/path/document 级 servers 覆盖及变量默认值。
仅选择一个媒体类型，不支持 multipart encoding、响应 header 完整建模；相对服务器需要文档来源 URL。
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
normalized_as、suggested_fix、semantic_loss。前端显示数量与处理摘要，再按条目展开详情。
未知 x-* 字段不写入 Canonical；源文档中保留原值，通过诊断位置回查。
源资源和无法表达的语义不混入 Canonical Schema，避免放宽内部允许列表。

Swagger 1.x 明确提示：

> Legacy Swagger 1.x is not currently supported; please convert to Swagger 2.0 or OpenAPI 3.x.

## 持久化、fingerprint 和 Diff

无需数据库迁移或 Canonical 版本变化；诊断存入现有 ImportRun.results JSON，旧结果默认 diagnostics=[]。
诊断不进入 ImportedOperation.content_fingerprint，import_key 仍由 method/path 生成。
规范化前后语义确有变化的接口（新增 formData Schema、collectionFormat、展开引用、partial 状态）
可能在首次重新导入时显示 changed；重复导入相同文档结果稳定。诊断和执行前缀 metadata 不进入 fingerprint。
媒体类型、参数覆盖、示例选择和来源地址修复可能形成合理的首次 Diff。

## 回归验证

`backend/tests/fixtures/importers/swagger2-compatibility.yaml` 是匿名最小 fixture，
精确覆盖两个真实故障 definition 的多行 description，以及上传、三个 multi 接口、path mismatch、GET body。
`test_openapi_compatibility.py` 覆盖三个版本、引用、组合、表单、安全边界和稳定性；
`test_imports_api.py` 验证 partial 导入诊断能通过实际 API 返回。
现有 Postman/HAR/cURL/Bruno 解析测试继续执行。

规范依据：[Swagger 2.0](https://spec.openapis.org/oas/v2.0.html)、
[OpenAPI 3.1.0](https://spec.openapis.org/oas/v3.1.0.html)。

## 三层能力矩阵（含 3.2）

FULL 只针对行内指定的子集。“可解析”不等于“契约完整”或“开箱可执行”。
3.2.x 的现代 Schema 投影沿用 3.1 的 2020-12 子集，不代表完整 3.2 实现。
3.9.x、4.x、冲突版本头和错误的显式导入格式会拒绝，不把任意 `3.*` 归到 3.0。

| 范围 | 可解析 | Canonical 表达 | 可执行 |
| --- | --- | --- | --- |
| Swagger 2.0 JSON/YAML | FULL | PARTIAL | PARTIAL |
| OpenAPI 3.0.x JSON/YAML | FULL | PARTIAL | PARTIAL |
| OpenAPI 3.1.x JSON/YAML | FULL | PARTIAL | PARTIAL |
| OpenAPI 3.2.x JSON/YAML | FULL | PARTIAL | PARTIAL |
| 基础 Schema、组合、nullable/type union | FULL | PARTIAL（严格允许列表） | PARTIAL（不是完整 Schema 校验器） |
| JSON / +json、普通 URL 编码表单 | FULL | FULL（单个选中媒体类型） | FULL（需可用环境与参数） |
| multipart 文本 + 单文件字段 | FULL | FULL（结构） | PARTIAL（文件必须由用户绑定） |
| multipart 数组 / encoding | FULL | PARTIAL + WARNING | UNSUPPORTED（需手动配置） |
| query 标量数组 multi/csv/ssv/tsv/pipes | FULL | FULL（tsv 为兼容样式） | FULL（JSON 数组变量；最多 1000 项） |
| query 对象/对象数组、复杂编码 | FULL | PARTIAL + WARNING | UNSUPPORTED（需手动配置） |
| basic / bearer / apiKey | FULL | FULL（单个 requirement） | PARTIAL（凭据需绑定） |
| OAuth、OpenID、AND/OR 认证 | FULL | PARTIAL + WARNING | UNSUPPORTED（默认阻止未配置认证） |
| servers/basePath/变量默认值 | FULL | PARTIAL（记录一个目标） | PARTIAL（用户环境优先） |
| 内部 Schema/参数/body/response/Path Item 引用 | FULL | PARTIAL（循环与预算截断诊断） | PARTIAL |
| definitions 名含斜杠的不规范引用 | WARNING（标准解析失败后精确修复） | FULL（目标存在时） | 按目标结构 |
| 缺失、远程、跨文件引用 | WARNING | PARTIAL | UNSUPPORTED（不联网、不读取旁边文件） |
| 2020-12 prefixItems/unevaluated/条件/dependencies/contains | FULL | PARTIAL + WARNING | UNSUPPORTED（未实现完整验证语义） |
| 自定义 dialect、$id scope、anchor、dynamicRef | WARNING | PARTIAL | UNSUPPORTED |
| 具体响应码/default | FULL | FULL（已支持 Schema 子集内） | PARTIAL（需测试断言） |
| 2XX 等响应范围 | FULL | PARTIAL + WARNING | UNSUPPORTED（不擅自推断 200） |
| callbacks/webhooks、vendor extensions | FULL | WARNING（源中保留） | UNSUPPORTED |

### 来源与执行规则

- URL discovery/fetch 的 document_url 进入解析和预览重放。Swagger 缺 schemes 时只从该 URL
  取协议；文件未知协议不猜 https。已有 endpoint 默认保留，显式确认地址更新时才覆盖。
- path/operation 参数先合并，再生成请求与契约。仅 header 名忽略大小写；`id` 与 `ID`
  是不同 query 参数。最终请求保留重复 query key。
- 标准 JSON Pointer 优先，包括百分号与 `~0/~1`。仅在失败后对 definitions 的精确完整键名
  修复未转义的 `/`；不模糊匹配，不从 Integer/List 等 Java 名推断类型。
- 媒体按 JSON 优先、名称排序选择；请求正文与契约使用同一选择。
- Swagger basePath 记录在现有契约 warnings metadata 中；只有目标已经包含这个明确前缀时
  才在执行拼接中去重，保留网关前缀和原始 import_key。
- partial 契约进入测试设计时增加未覆盖条目和审核要求。MCP 返回相同诊断与审核建议。
- 无数据库迁移；版本族、诊断和前缀 metadata 使用现有 JSON 字段。旧记录缺省 diagnostics=[]。

## 本轮验收边界

新增 `test_openapi_semantics.py` 和导入 API 集成用例，覆盖 3.2/未知版本、JSON/YAML、
9 个可修复引用与 5 个真正缺失引用、参数大小写覆盖、媒体选择、Path Item、来源协议、
服务器覆盖、认证缺口、响应范围、运行时数组 mock HTTP 和网关前缀。
未获得完整公司 Swagger 样本，也未找到提示词提及的附带最小 JSON；沿用匿名 fixture
并新增合成文档。**不能报告 737 个真实接口全部验收通过。**
本次实际测试结果见 `OPENAPI_IMPORT_ACCEPTANCE.md`。

规范参考：[OpenAPI 3.0.4](https://spec.openapis.org/oas/v3.0.4.html)、
[OpenAPI 3.2.0](https://spec.openapis.org/oas/v3.2.0.html)。
