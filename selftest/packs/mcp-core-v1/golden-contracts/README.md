# 本轮冻结契约

实际运行时从隔离 B 读取 OpenAPI 和所选 API 发布版，保存规范化内容摘要及真实 API ID、版本和契约指纹。文件不预置最终 Workflow、Case 或历史 UUID。

`generation-tasks/core.json` 只定义任务和独立行为要求。`expected-behaviors/core.json` 定义稳定必测分母与 canary 语义；具体断言节点由独立检查在运行前冻结。任何缺少输入、来源或无损转换能力的任务保持阻断，不改黄金预期。

动态批次使用 `selftest/schemas/manifest.schema.json`，证据使用 `evidence.schema.json`，核验产物使用 `verification.schema.json`。这些 schema 是本次新增的本地 Harness 协议，不是既有产品 API。
