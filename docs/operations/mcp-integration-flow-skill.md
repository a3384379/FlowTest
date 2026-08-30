# FlowTest 集成流程生成 Skill

`flowtest-generate-integration-flow` 是 V6.0 Core 唯一旗舰 Skill。它让支持 Skills 与 MCP 的外部 Agent
按照固定顺序汇集授权证据，生成 FlowTest 的待审核集成流程提案，并把最终决定留在既有 Visual Review。
它不替代 FlowTest 权限、审核、Apply、Publish 或执行边界。

## 安装

Skill 包位于仓库的 `skills/flowtest-generate-integration-flow/`。将整个目录复制到 MCP 客户端支持的
Skills 目录，目录名必须保持不变。发布或安装前可在 FlowTest 仓库根目录验证：

```bash
python /path/to/skill-creator/scripts/quick_validate.py \
  skills/flowtest-generate-integration-flow
```

Skill 的 `manifest.yaml` 是机器可读契约；`SKILL.md` 是 Agent 入口；`references/` 只在相应步骤加载。
安装不得改写 Manifest 中的最小 MCP 版本、Tool、Scope、审批点或 Stop Conditions。

## 前置条件

- FlowTest MCP Server 至少为 `s55-sandbox-preview-v1`；stdio 与 Streamable HTTP 均支持。
- Service Account 至少具备 `mcp:read`、`mcp:evidence:write`、`mcp:flow:propose`。
- 可选 Sandbox Preview 另需 `mcp:preview:execute` 和由 Owner 签发、绑定当前 Service Account 与 Proposal
  的一次性 Approval。
- 用户必须明确选择一个有权访问的项目、业务流范围和非生产测试环境。
- Code MCP、Database MCP 由外部 Agent 分别连接；FlowTest Server 不发现、不认证、不保存这些 MCP
  的地址或凭据。

## 标准流程

```text
选择项目
→ 创建版本固定的 Context
→ 检查 Missing Evidence
→ 外部只读 Code/DB MCP 或脱敏导出物补证
→ Ingest Typed Evidence
→ 再次检查 Conflict / Missing / Revision
→ Plan
→ Validate
→ Compile
→ Validate FlowSpec
→ Dry Run
→ Propose Draft
→ Visual Review
→ 可选 Sandbox Preview
```

每个阶段必须携带上一步返回的 Context Revision、Evidence Ref、Plan/Compilation Fingerprint 和 Proposal
ID。发现 Revision 过期时重新读取并展示差异，不能覆盖；发现证据冲突时保留双方来源并停止，不能猜测。

## Visual Review 与 Preview

`propose_flow_draft` 只创建待审核提案。正常 Skill 流程在提示用户进入现有 Workflow Designer 的
Visual Review 后结束，不代替用户 Accept、Apply 或 Publish。

Preview 是单独的可选分支。只有用户明确请求、Environment 分类为 `test`/`sandbox`、Approval 未过期且
未消费、执行预算和 Cleanup 均有效时才可调用。`production` 或未分类环境硬拒绝；Cleanup 任一步失败都
必须作为失败报告，不得降级成 Warning。

## 安全边界

- 只接收有界、强类型、带版本和 Provenance 的 Evidence；不接收原始仓库、数据库行、连接串或可执行代码。
- 请求值、响应 Body、Token、Cookie、Secret 与 PII 不进入 Skill 输出；凭据只使用 `secret://` 引用。
- Database MCP 只提供 Schema、关系、约束、索引、枚举摘要和脱敏聚合画像；不运行写 SQL。
- 外部 MCP 输出视为不可信数据，不作为指令执行。
- 不存在 Publish、生产执行、权限修改、Credential 创建、任意脚本、写 SQL、删除或自动 Repair Tool。
- 不得通过弱化断言、忽略 Conflict 或修改预期结果来“修复”产品缺陷。

## Golden Evaluation

运行模型无关评测：

```bash
uv run --project backend python scripts/evaluate_v6_core.py --check
```

当前小型 Golden Set 的 Operation Candidate Precision 为 `3/3`，Binding Candidate Precision 为 `2/3`；
它们只是固定 Fixture 的基线，不是总体准确率，也不支持“95% Accuracy”宣称。发布硬门槛使用精确分母，
空分母为 `insufficient_evidence`。提交的 Compiler、Preview、Conflict Detection 与 Static Validation 为
`1/1`；Secret Leak、Cross-Tenant、Stale Overwrite、Unreviewed Apply、Production MCP Preview、Arbitrary
Code、Write SQL、Cleanup Silent Failure 与 Product Defect Auto-Weakening 均为 `0/1` 事件率。

## 升级与回滚

Skill 本身没有数据库状态。升级时整体替换目录，并核对 `manifest.yaml` 的 Version 与 Minimum MCP Version；
回滚时恢复上一完整目录，不混用不同版本的 `SKILL.md`、Manifest 和 References。FlowTest 应用、Standalone、
Compact、Full、Backup/Restore 与 Upgrade/Rollback 仍按各自运行手册和 CI 证据验收。
