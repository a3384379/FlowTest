# ADR 0017：AI 建议、人工审核与数据边界

## 状态

已接受（S21）

## 决策

1. AI 默认关闭，只通过 OpenAI-compatible 网关接入；未配置网关时不得影响现有 API、Workflow、计划或报告能力。
2. AI Job 进入独立 Celery `ai` 队列。API 只创建持久任务并返回 `202`，Provider 调用不占用 API 请求生命周期。
3. 默认输入仅包含 Schema、字段描述和经过统一规则脱敏的元数据。项目 Owner 可显式开启样本共享，但每次提交仍重新脱敏；Editor 和 Viewer 不能提交样本。
4. Password、Authorization、Cookie、Token、Secret、API Key、Bearer、Basic 和 JWT 在离开平台前被替换。Provider API Key 不进入任务输入、日志、数据库或审计明细。
5. Provider 必须使用固定 JSON Schema 2020-12 严格输出。任务类型限制可接受的建议类型，响应还需执行本地 Schema、大小和二次脱敏校验。
6. 建议初始状态固定为 `pending`。用户可逐项接受、编辑后接受或拒绝；只有接受的 Test Case/Workflow 建议才能创建可修改草稿。
7. AI 不得发布版本、触发执行、创建 Credential、修改权限或改变已发布资产。重复审核返回冲突，重复 Worker 执行保持既有终态。
8. 审计记录模型、提示模板版本、输入摘要 SHA-256、Token 用量、脱敏路径和接受/拒绝结果，不保存原始敏感输入。
9. 发布候选使用离线、确定性的脱敏评测集验证隐私边界；真实模型质量评测必须使用不含 Secret 的专用样本，并由人工确认结果。

## 结果

- AI 能力可独立关闭、扩缩和失败，不改变核心测试平台可用性。
- 建议从生成到资产落库始终保留人工决策点和可追溯审计。
- Schema 与脱敏规则是调用网关前后的双重信任边界，畸形响应不会成为可执行资产。
- V2 继续禁止任意脚本和 AI 自动执行，为 V3 的 AI Change Set 保留受控扩展点。
