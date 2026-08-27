## Scope 与 Non-goals

- Scope：<!-- 本 PR 唯一阶段和可验证交付 -->
- Non-goals：<!-- 明确不在本 PR 实现的能力 -->

## 兼容、Migration 与 Rollback

- [ ] API / Contract / Fingerprint / Snapshot 兼容影响已说明
- [ ] 数据库变更包含 Alembic upgrade/downgrade；无数据库变更时已注明
- [ ] Standalone / Compact / Full 兼容影响已验证或标为不适用
- Rollback：<!-- 回退步骤、数据可逆性与触发条件 -->

## 数据、安全与可观测性

- [ ] 新字段已标记数据分类、加密、Rotation、Retention、Export、Support Bundle 与 Redaction
- [ ] 未记录或返回 Password、Authorization、Cookie、Token、Secret、PII 或未脱敏敏感正文
- [ ] 外部错误使用标准错误信封并包含 Trace ID
- [ ] 外部 URL、文件、文档、Workflow/Template 和 Evidence 均按不可信输入处理

## 四维 Review

- [ ] 正确性与边界条件
- [ ] Security / Authorization / Tenant 隔离
- [ ] Compatibility / Migration / Rollback
- [ ] Operability / Observability / Documentation

## 验证方式

- [ ] Backend：format、ruff、mypy、pytest
- [ ] Frontend：format、lint、coverage、build
- [ ] Compose Playwright E2E 或说明不适用原因
- [ ] Golden / Roundtrip / Migration / Failure-path（按变更适用）
- 证据：<!-- 命令、CI Run、截图或 Trace；不要粘贴 Secret -->

## 风险、审批与 Review Thread

- 风险：<!-- 失败模式、影响范围、监控与停止条件 -->
- [ ] 高风险操作具备明确人工审批；本 PR 未扩大既有 Scope/权限
- [ ] 所有 P1/P2 与未解决 Review Thread 已回复证据并关闭
