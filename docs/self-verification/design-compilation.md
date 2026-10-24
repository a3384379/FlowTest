# 固定 Test Design 的只读编译

本增量将前次生成的 Design、实际 API 版本与原生流程转换相连。编译不创建资产、提案或执行，不调用目标，不审核或发布；既有 REST Test Engineering 的审核、版本变化拒绝和应用行为保持不变。

## 入口与版本来源

- MCP：`flowtest.compile_test_design(request=...)`。
- 网关：`POST /api/v1/mcp/flow/designs/compile`。
- 机器主体必须同时具备 `mcp:read` 和 `mcp:flow:propose`；任一缺失均拒绝。
- `generate_test_design`、覆盖分析和证据检查增加可选正整数 `api_version`。未传时解析当时的 current version；响应的实际版本始终明确返回。
- 普通 REST 生成响应和 MCP 生成响应中的 `origin` 包含 API ID、实际版本、契约指纹、生成策略、证据及其指纹、生成器实现摘要。原有 `design`、`fingerprint`、`persisted` 保留。
- `generator_build` 是当前生成器模块源码的 SHA-256，用于编译时检查实现身份；它不是部署镜像、可信 CI 或整个构建的证明。部署构建身份仍由外层验收记录。

## 输入和拒绝规则

请求提交原样的 `design`、`design_fingerprint`、`origin`，非空且唯一的 `scenario_ids`，已授权 `environment_id`，以及可选的 Endpoint Variant、Context 绑定和有界预算。Context 绑定使用真实响应的 `id`、`revision.id`、`revision.fingerprint`，且必须是当前、就绪、未过期、内容摘要一致的 Revision。

服务按明确的 API 版本读取契约，校验所属项目、契约指纹与实际 method/path，再使用冻结的策略和证据重新生成并比较 Design 指纹。变更过 Design、证据或生成器身份，不能继续冒充原生成结果。编译历史版本不改变原有 REST 提案在应用时拒绝 current version 漂移的规则。

服务器上限为 50 个场景、500 个节点、200 个 Oracle、2 MiB 请求体和 3600 秒总运行预算；请求可以进一步缩小。证据最多 10 包、2 MiB，Design 最多 4 MiB。每个输出流程固定一次请求预算，并将总时长预算分配到所选场景；FlowSpec v2 保留这些原生运行约束。

## 输出与后续交接

响应为强类型 `flowtest-design-compilation-v1`，明确 `persisted=false`、`execution_status=not_run`。它包含实际来源、编译指纹、全部所选场景和逐项 diagnostics。就绪状态优先级为 `blocked → unsupported → needs_review → needs_input → ready`；局部可编译不代表完整请求成功。

当前可用路线是共享的原生单场景 lowering，再通过已有转换器输出 FlowSpec v2：

1. 使用 `scenarios[].executable_payload.spec`、`operation_mappings` 和 `operation_version_mappings`，连同真实 Context ID/Revision，交给现有 `flowtest.propose_flow_draft`。
2. 该现有工具同时支持独立 `spec` 与原来的成对 `integration_plan`/`compilation`。缺少配对、没有任一来源或两种来源不一致时拒绝，不向网关提交冲突内容。
3. 沿既有页面人工审核、应用到 Workflow 草稿，再显式发布并读回真实 Workflow ID 和版本。
4. 将 `case_template.workflow_slot` 映射到该真实发布版本，才可创建正式 Case 提案。slot 只是编译包内关联键，不能作为 TestCase 的合法 Workflow ID。

每个受支持 Oracle 都返回 `oracle_id → node_id`、来源节点、实际断言类别、规范化表达式和期望值摘要。状态映射为 `assert_status / status_code`，Schema 映射为 `assert_schema_N / body`，字段比较映射为 `assert_expression_N`。独立核验仍以受保护的外部 manifest 为预期来源，不能用编译说明自证结果。

## 当前明确不支持的组合

- Quick 或 native control 路线偏好、4.0 控制区转换。
- 根 body 的 null 与未提供之间无法精确区分的请求；嵌套对象内的 null、0、false、空串按原值保留。
- 重复参数、path 请求变异、额外 fixture 和认证子流程绑定。
- 改变冻结场景认证语义；`disabled` 绑定只能用于本来已禁用认证的场景。
- 未审核、非确定性、缺少唯一状态码依据、不受支持的 Oracle 或无效表达式/Schema。

缺少 Context 时返回 `needs_input`，并保留可检查的编译产物；不会把这种结果标为可直接提交提案。正常业务负向场景仍预期原生执行 passed；坏目标故障注入的预期失败由外部 manifest 单独定义，不能改写原始执行状态。

## 实现与定向验证

共享 lowering 位于 [领域模块](../../backend/app/domain/test_design_lowering.py)，旧 REST 服务通过错误适配保留原错误码；新增编译的 [领域契约](../../backend/app/domain/test_design_compilation.py) 和 [授权服务](../../backend/app/services/test_design_compilation.py) 分离。实际 MCP input/output schema 和 annotations 的摘要保存在 [工具契约基线](../../backend/tests/fixtures/v6_golden/mcp-schema-fingerprints.json)，并通过现有构建脚本同步到五个独立 Skill 包。

已验证：提取前的行为 characterization、负向状态及 suppression、Schema/字段 Oracle、假值保真、严格输入和预算、双 scope、跨项目、来源/Context 漂移、历史版本、只读资源计数、真实 SDK 的独立 FlowSpec 提案交接、既有 REST 和 Skill 契约回归。完整日志与本轮执行边界由总交付记录汇总；这些定向检查不代表远程 Gate、真实外部宿主或完整发布验收通过。
