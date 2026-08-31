# ADR 0047：Context Inspector 的项目只读视图边界

## 状态

已接受，V6.1 S57 起执行。

## 背景

S57 的 Built-in Java/Spring Provider 和 State Knowledge 已把结构化 Evidence、完整性、冲突与证据派生图写入
不可变 Context Revision，但这些信息主要通过 MCP 响应和底层 API 暴露。项目用户需要在 Web 中检查当前
Revision、缺失证据、Provider Finding、State Candidate 以及关联 Flow Proposal，且不能因此扩大 MCP
Service Account 的写入 Scope，也不能建立第二套 Context 或 Proposal 生命周期。

Finding Statement、Warning、Subject Reference 和 Knowledge Label 均来自不可信目标源码或外部证据。读取页面
必须继续按项目授权隔离，并把这些内容仅作为文本展示，不能执行 HTML、脚本、模板表达式或目标代码。

## 决策

- 新增项目用户只读接口 `GET /projects/{project_id}/contexts` 与
  `GET /projects/{project_id}/contexts/{context_id}`。接口使用现有 Web 用户身份和 Project Read 授权，不接受
  MCP Service Account Token，也不复用或扩大 `mcp:evidence:write`、`mcp:flow:propose` 等 Scope。
- 页面只读取 `TestContext.current_revision` 指向的不可变 Revision。列表返回分页摘要和聚合计数；详情返回
  Completeness、Conflict、Provider、Evidence、Knowledge 与 State Candidate，不复制 Evidence Payload 或建立
  可变缓存。
- 过期状态按读取时刻计算并返回，但 GET 不修改持久化状态，不制造只读请求的隐藏写入。
- 关联 Flow Proposal 复用现有 `AIChangeSet`，只选择同项目、`source_type=flow_spec` 且
  `source_snapshot.context_revision_id` 匹配当前 Revision 的记录。页面深链到现有 Proposal Review，不增加新的
  Review、Accept、Apply 状态机。
- Evidence 列表的 Finding、Warning 和 Reference 使用普通文本组件展示；不得使用未净化的 HTML 注入，也不得
  根据展示内容执行网络请求或代码。
- Context Inspector 不创建、更新、关闭 Context，不 Ingest Evidence，也不接受/Apply Proposal。所有写入仍走
  原有 MCP 或 Proposal Review 授权链路。

## 结果

项目用户可以从“上下文检查器”完成以下只读检查：

```text
Context → Current Revision → Evidence/Conflict → State Knowledge → Flow Proposal
```

浏览器入口不要求用户持有 MCP 写入 Scope；跨项目 Context 仍返回标准 Not Found。Proposal 深链进入既有流程编排
审核界面，审批与 Apply 继续使用原有授权和安全检查。

## 否决方案

- 为浏览器用户签发或复用 MCP Evidence 写入 Scope。
- 为 Context Inspector 建立独立 Evidence、Knowledge 或 Proposal 表和生命周期。
- GET 请求为了标记 Expired 而更新 Context。
- 在页面中渲染外部 Finding 提供的原始 HTML、脚本或可执行模板。
