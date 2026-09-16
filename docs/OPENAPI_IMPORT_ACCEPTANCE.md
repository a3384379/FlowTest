# Swagger / OpenAPI 增量验收记录

## 基线与根因复核

基线为 PR #102 合并提交 `7dbe3fc7e8dcc4515e01f6638ff85382b9c93fc5`。
原始多行 description 问题已由 SourceNormalizer 处理，Canonical Validator 仍严格拒绝控制字符。
本轮不重复替换换行修复，也不修改脱敏策略。

只读复核确认仍存在以下缺口：

1. `3.*` 检测不能准确表达 3.0、3.1、3.2 差异，显式选择格式绕过版本检查。
2. 不规范的 definitions 引用和真正缺失引用缺少区分。
3. 下载文档 URL 未进入解析，缺 schemes 时错误猜测 https。
4. 请求参数直接拼接，而契约对所有名称忽略大小写，导致覆盖和 query `id/ID` 不一致。
5. 请求和契约分别选择媒体类型，可能发送与契约不同的正文。
6. 运行时数组未应用 Canonical style/explode，basePath 可能重复拼接。
7. 响应范围、认证组合等能力缺口未准确传递到执行、MCP 和测试设计。

## 实现边界

`Source + document_url → 明确版本族 → OperationAdapter → SourceNormalizer → Canonical → Strict Validator → Diff`

- `openapi_dialects.py`：已知版本族和显式格式校验。
- `openapi_normalization.py`：标准引用优先、definitions 斜杠精确修复、3.2 现代 Schema 语义及 semantic_loss。
- `openapi_adapter.py` / `openapi.py`：有效参数、Path Item 引用、服务器覆盖、媒体选择、响应及认证诊断。
- `parameter_identity.py`：header 忽略大小写，其他参数名称区分大小写；契约校验与排序共用。
- `import_execution.py` / `api_assets.py` / `request_targets.py`：数组序列化、已记录前缀去重、未配置认证阻止执行。
- `imports.py`：来源 URL 保留到预览重放；用户现有 endpoint 默认优先。
- MCP schema/service 与 `test_engineering.py`：诊断可见、partial 契约保留覆盖缺口和审核要求。
- `ImportDialog.tsx`：摘要及逐条展开详情。

没有新表、破坏性迁移或 Canonical 版本升级。现有 ImportRun.results 与契约 JSON 承载兼容信息。
`import_key` 仍由方法和路径生成。诊断与执行前缀 metadata 不影响 content fingerprint；修正后的实际
媒体、参数和目标行为会形成有原因的首次 Diff。重复输入保持稳定。

## 测试命令

后端在 `backend` 目录执行，使用已有虚拟环境并设置 `PYTHONPATH=.`：

```sh
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync mypy app
uv run --no-sync pytest
uv run --no-sync pytest tests/test_openapi_semantics.py tests/test_openapi_compatibility.py tests/test_importers.py tests/test_imports_api.py tests/test_import_url_fetcher.py tests/test_importer_secret_boundaries.py tests/test_redaction_policy_off.py tests/test_s61c_contract_import.py --no-cov
```

前端在 `frontend` 目录执行：

```sh
pnpm format:check
pnpm lint
pnpm test:coverage
pnpm build
FLOWTEST_E2E_BASE_URL=http://127.0.0.1:13010 pnpm exec playwright test e2e/openapi-import-compatibility.spec.ts --project=chromium
```

Playwright 使用独立 `flowtest-openapi-semantic` Compose 项目及新建数据库，挂载本轮后端代码和
前端构建产物。仅导入匿名 fixture、预览 Diff，不执行真实业务接口。原工作区和原 Compose 服务未修改。

## 已完成验证

- Ruff 格式及 lint、mypy 通过。
- 最终导入专项回归：164 passed，包含现有 Postman/HAR/cURL/Bruno/Excel 和脱敏边界相关测试。
- 前端：84 个测试文件、385 项测试通过；行覆盖率 88.02%，分支覆盖率 80.54%。格式、lint、构建通过。
- Playwright：2 passed（登录初始化与匿名 Swagger 导入）；八个接口进入 Diff，诊断可展开。
- 后端全量：1445 passed、7 skipped，覆盖率 90.68%；最后新增的多 consumes 表单回归包含在上述
  164 项专项结果中。GitHub 最新提交全量检查仍是合并的必要条件。

## 尚未验证或完整支持

没有获得完整公司 Swagger 文件，不能报告 737 个 operation 真实验收通过。使用的 9 个斜杠引用和
5 个缺失模型为合成输入；缺失模型保持 partial，没有从 Java 类型名猜测 Schema。

完整 JSON Schema 2020-12、动态/外部 URI scope、跨文件/远程引用、复杂认证授权、multipart encoding、
文件数组、复杂 query 对象、响应范围的完整语义尚未实现。已区分诊断和可执行边界，详情见
[兼容性矩阵](OPENAPI_IMPORT_COMPATIBILITY.md)。不部署真实环境，也不声称本轮完成生产验收。
