# ADR 0053：MCP 组织级项目初始化与测试目标边界

状态：Accepted（S61B）  
日期：2026-09-08

## 背景

MCP Closed Loop 需要支持一个尚未在 FlowTest 建立项目的组织完成测试接入。既有
`IdempotencyRecord` 必须带 `project_id`，不能用于第一个项目；同时普通项目创建权限和
服务账号的 MCP 权限不能互相推断。环境、Service 和 Endpoint 还必须继续服从项目的出站
网络、TLS、凭据和环境分类治理。

## 决策

1. 为首个项目和后续初始化操作增加独立的 `OrganizationIdempotencyRecord`。回执按组织、
   服务账号、操作和幂等键唯一；项目建立后仍使用既有项目级幂等语义。禁止 dummy project、
   虚构 UUID 或先裸创建再补 Claim。
2. 为 `Project` 增加组织内唯一的可选 `external_key`。解析顺序为显式 `project_id`、
   `external_key`、唯一名称；名称多匹配时返回 `AMBIGUOUS_PROJECT`，不取第一条。
3. 新增专用 Scope `mcp:project:bootstrap` 和三个 MCP 工具：
   `flowtest.ensure_project`、`flowtest.ensure_test_environment`、
   `flowtest.ensure_service_target`。工具默认 Dry Run；真实写入要求有效服务账号、固定组织、
   Scope 和 `Idempotency-Key`。
4. 初始化只允许创建/复用项目、`test`/`sandbox` 环境及 Service Endpoint 元数据。已有
   配置不被改名、改址、降级分类或重置策略；不接受密码、Token、认证 Header、secret 明文，
   不借初始化扩大出站白名单。TLS 校验固定为开启。
5. 环境初始化可以创建默认 Service/Endpoint 作为同一产品服务的最小元数据；Service Target
   后续复用同一 Service/Endpoint 模型，不创建第二套路由或导入系统。

## 事务与恢复

每个 ensure 操作独立幂等。组织回执先 Claim，再在同一操作事务中创建资源并保存完成回执；
原子失败会释放未完成 Claim，已完成回执可在后续业务状态变化后按原结果恢复。数据库唯一约束
处理不同幂等键并发创建，冲突时只回读组织内同一资源。跨步骤不自动删除已创建资源，调用方可
使用下一步 ensure 继续。

## 验收边界

覆盖空组织 Dry Run、同键重放、不同参数冲突、不同键复用、无权限/缺 Scope、环境分类和目标
冲突、TLS/敏感 URL、MCP 连接 action、严格未知字段、MCP Golden、Alembic/Standalone 基线
与 Skill 评测副本。隔离 API 测试不代表真实宿主 MCP 或真实 LLM 验收；后续 S61C 复用这些资源
进入受控契约导入管线。
