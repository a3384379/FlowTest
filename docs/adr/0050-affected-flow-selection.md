# ADR 0050：复用现有影响分析的 Affected Flow

状态：已采纳（S59B）

## 决策

- 以纯领域 Operation Selector 和版本内知识图遍历产生影响候选。服务仅查询既有 Workflow、API、
  Context Revision 与可选 ImpactRun；不创建维护任务表、Proposal、幂等记录或自动执行流程。
- 接口为 `GET /projects/{project_id}/contexts/{context_id}/affected-flows`，显式传入
  `before_revision`、`after_revision`，可选 `impact_run_id`。复用 Context Inspector 的项目读取授权、
  历史版本归属验证；ImpactRun 也必须属于同一项目。
- 复用 S45 Change Regression 的 Operation Identity 解析。普通 API 和 `http.request@2.0.0`
  均读取有效配置。固定版本不存在时报告未解析，不回退 current；同一次请求缓存实际解析结果。
  Runtime Service Override 不替代契约的 Service Identity。
- 已知 Definition ID、Version、Service、Portable Ref、Method、Path 或 Fingerprint 冲突时不做路由回退。
  ID + Version 为实例匹配；完整 Service/Portable/Method/Path/Fingerprint 为 Portable 匹配；
  仅 Method/Path 相同为待复核候选。契约基线或当前指纹均可识别受影响流程，不改变 S45 的新测试选择规则。
- Before/After 图分别遍历，包含删除节点和关系，不拼接两个版本的路径。循环按已访问状态有界遍历。
  仅明确关系白名单可形成显式关联；`may_*`、未知关系与 `requires_review` 节点降为启发式候选。
  多值冲突身份不覆盖，输出 `KNOWLEDGE_IDENTITY_AMBIGUOUS`。
- 复用 Impact 已持久化的 Workflow 选择，返回独立的 `explicit_asset` 原因及所选资产版本；
  同一流程不同版本不互相覆盖。它是既有选择证据，不代表当前草稿与该发布版本完全一致。
- 响应不复制节点标签、普通 Fact 值、源码、请求正文或 Impact 原始解释；仅返回身份、引用和固定诊断码。
  所有结果固定 `requires_review=true`、`automatic_patch_allowed=false`。

## 完整性与边界

- 分页默认 20、最多 50 个当前项目 Workflow，按 UUID 排序。返回总数及实际扫描 ID；单页空结果不能
  代表项目无影响。草稿超过 200 节点在解析前拒绝分析，单流程理由超过 100 项显式报告截断。
- 无效配置、缺失 API、Subflow/ForEach、SQL/Redis、未支持 Capability 都报告未覆盖；本阶段不递归
  展开其他流程，也不声称完成 GraphQL/gRPC 语义选择。
- S59C 补充请求级上限：500 个节点、100 个唯一 API/版本身份解析、100,000 次候选比较；耗尽时返回
  `ANALYSIS_BUDGET_EXCEEDED`，停止继续扫描，并记录实际已扫描流程。显式关系包含 Kafka `consumes`。
  内部目标工作流分析返回 `analysis_scope=workflow` 和目标 ID，不将单目标结果误称为全项目扫描。
- Context 发生变化时保守报告 `CONTEXT_CHANGE_UNMAPPED`：结构关联不能证明所有 Evidence/Provider
  改动都已覆盖。该诊断不否定已返回的匹配；后续 S59D 结合 Current TestPlan Gap 解释剩余缺口。
  `analysis_complete` 只表示该请求已完整扫描且无未覆盖诊断，不代表可自动 Patch 或 Release Gate 通过。
- S59C 才负责可信 Maintenance Provenance、白名单 Patch、人工 Review/Preview/Apply，并收口 PR #82
  来源标签 P2；S59D 接入既有 Change Regression Snapshot，不建立第二套生命周期。
