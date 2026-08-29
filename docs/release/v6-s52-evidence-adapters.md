# FlowTest V6.0 S52 External Evidence Adapter 与 Entity Mapping

## 1. 阶段身份

| 项目               | 当前值                                                                 |
| ------------------ | ---------------------------------------------------------------------- |
| 阶段基线 Main SHA  | `b6c281a832ec63e94433e0f322b30b6e342098c1`                             |
| 实现分支           | `codex/v6-s52-evidence-adapters`                                       |
| MCP Server Version | `s52-evidence-adapter-v1`                                              |
| Scope              | `mcp:evidence:write`                                                   |
| 数据库变更         | `20260829_0047`；扩展 Evidence Provider 来源约束                       |
| Release 状态       | PR #58；最新 Codex Review 修复与精确门禁复验中                         |

S52 从 S51 Evidence Closure 合并且精确 Main Push Required Gate 全绿后的 Main 创建。External Code MCP 与
Database MCP 把强类型证据提交给 FlowTest；FlowTest 不主动连接任意外部 MCP Server。

## 2. Implemented

### Java 与 DB Evidence Contract

- `flowtest-java-evidence-v1` 使用判别联合表达 Controller Route、DTO Field、Bean Validation、Service Call、
  Feign Call、Mapper/Repository、Entity、Table/Column、Enum/State、Exception 与 Kafka Event。每条 Claim 都有
  Source Path、Confidence 与 Deterministic，Submission 强制显式 Source Revision。
- `flowtest-database-evidence-v1` 表达 Schema、Table、Column、PK、FK、Unique、Nullable、Enum、Check、
  Observed Distribution 与 Masked Example。契约没有 SQL 执行字段；Check Expression 中的写入或 DDL 关键字被
  拒绝，运行期 DB 校验仍继续使用既有只读 SQL Node。
- 两类专用 Contract 都转换为既有 `flowtest-external-evidence-v1`，写入 S49 的不可变 Context Revision 与
  `ContextEvidenceItem`。未新增表、Revision 状态机或旁路持久化。
- Migration `20260829_0047_evidence_provider_provenance` 扩展 `test_context_evidence_items` 的 Provider Type
  约束，允许 Repository/Database 以及 S51 已声明的 Service Topology、Change Analysis 与 User Confirmed 来源；
  Standalone 基线、既有 SQLite 表重建和 Storage Transfer Revision 同步到 Head `20260829_0047`。Downgrade 会先按
  外键级联删除含新增 Provider Type 的 Context，再恢复 `20260828_0046` 的旧约束，Upgrade/Downgrade 路径均有回归。
- External Finding 的 `structured_data` 使用按 Adapter 与 Claim Kind 判别的封闭类型联合，未知字段、未知 Java/DB
  Claim 或 Claim Kind 与 Payload 不一致都会在 API 边界拒绝；空结构沿用旧 Fingerprint 输入，保持 S49 既有
  Envelope 的语义指纹兼容。既有 Python AST Provider 的 `EvidenceBundle` 通过只保留强类型元数据与原始结构指纹的
  兼容适配器进入同一 Context 主路径，不把其任意字典重新暴露为外部契约。

### Entity Mapping

- 输出四类强类型候选：Operation → Entity、Request Field → Column、Response Field → Column、Operation →
  State Set。每个候选都携带稳定 Candidate ID、Confidence、Deterministic 与一个或多个 Context Evidence Ref。
- Java DTO camelCase 与 DB snake_case 只做确定性规范化匹配；Operation/Entity 关联使用显式 Entity/Table Claim，
  或降级为可见的资源名启发式候选。
- 所有自动结果状态固定为 `proposed`。同一 Source 出现多个 Target 时生成 `EntityMappingConflict`，不静默选中；
  专用 Evidence Ingest 会同时把新歧义写为 Conflict Finding，使 Context 状态进入 `conflicted`。
- Java Enum 与 DB 状态列给出相同 State Set 时合并其 Evidence Ref，并按最小 Confidence 与全部 Deterministic
  的保守规则组合；DB Finding 的低置信度或非确定性不会被抬高。不同表或不同 Target 仍保留为歧义。
- DB Boolean 状态值按 JSON 标准统一为小写 `true`/`false`，与 Java Enum Claim 的字符串表达一致；等价证据不会因
  Python `True`/`False` 文本化差异制造阻断提案的假冲突。
- Envelope 与持久化 `ContextEvidenceItem` 的有效 Confidence/Deterministic 会传播回 Java/DB Claim，并同时
  约束 Operation/Entity、Field/Column 与 State 候选；Revision 重建不会恢复为 Finding 中的较高原始值。
- Entity Claim 的确定性显式参与 Operation/Entity 候选；Operation→Table 关联的 Confidence/Deterministic 与
  Evidence Ref 继续约束依赖它的 Field/Column 和 DB State 候选，路径启发式不会被下游抬高。
- Route 没有显式 Operation/Entity 关联时只回退到未绑定 Operation 的 Entity；已声明其他 Operation Ref 的
  Entity 不会被跨 Operation 当作确定性映射。
- Operation 存在显式 Entity 时禁用 Route/Table 名称启发式，显式 `table_ref` 也优先于 Class Name 回退；其他
  Operation 已声明的 Entity/Table Ref 会阻断 Route 与 Field/Column 回退，不能生成跨 Operation 候选或假冲突。
- Entity 显式 Table Ref 同时支持 `table://schema/table` 与既有 Fixture 使用的 `table://schema.table`；两者都按
  Schema/Table 与 DB Evidence 精确匹配，不会误降级为 Class Name 启发式或跨 Schema 误关联。
- Java `table_column` 显式声明优先约束 Field/Column 候选，支持不同命名的 Field 与 Column；声明自身的
  Evidence Ref、Confidence 与 Deterministic 会参与候选，且同名字段按 Operation 关联的 Entity 隔离；无显式
  Operation→Entity 候选时，也不会吸收已绑定其他 Operation Entity 的 Column Claim 或对应 DB Table。
- DB `claim_kind=table` Finding 作为独立强类型映射输入；即使 Envelope 没有 Column Finding，显式 Java Entity
  仍可生成带 Table Finding Evidence Ref 的 Operation→Entity 候选。Column 只作为补充证据，不再代替 Table Claim。
- Operation State Source 由 Operation 与 Field 共同确定；Java camelCase State Field 与 DB snake_case 状态列按
  规范化字段名相关联。同一 Operation 的独立 State Field 不互相制造假冲突，同字段不同 State Set 仍保持歧义。
- DTO Field Source Ref 包含完整 Operation Ref 的 SHA-256 身份；同一 DTO Field 被不同 Operation 合法复用时不产生
  跨 Operation 假冲突，同一 Operation 内的多 Target 歧义仍保持可见。
- Candidate ID 只取决于 Mapping Kind/Source/Target/Operation/Field/State 语义；新增佐证只合并 Evidence Ref，
  不改变同一候选身份。Candidate Budget 在按 ID 增量去重后计算，重复 Revision 的笛卡尔积不会误报超限；相关
  Evidence、唯一 Candidate 与 Conflict 超出有界预算时返回标准
  `ENTITY_MAPPING_BUDGET_EXCEEDED` 422，不截断或静默漏掉候选。

### API 与 MCP

- REST：`POST .../{context_id}/java-evidence`、`POST .../{context_id}/database-evidence`、
  `GET .../{context_id}/entity-mapping`。
- MCP：`flowtest.ingest_java_evidence`、`flowtest.ingest_database_evidence`、
  `flowtest.inspect_entity_mapping`。三者继续使用 `mcp:evidence:write` 与既有 Tenant/Project 授权。
- Ingest Response 同时返回脱敏 Context 摘要与当前 Mapping；Inspect 从当前不可变 Revision 复算相同结果。
- 既有通用 `ingest_external_evidence` REST/MCP 入口接收强类型 Java/DB Adapter Payload 时，也执行同一映射
  冲突派生；不能借通用入口使存在歧义的 Context 保持 `ready`。
- Mapping Conflict Marker 必须同时为 `kind=conflict` 与 `semantic_role=conflict`才能抑制重复合成；伪装成
  Normative 的外部 Marker 在合同边界被拒绝。新冲突数超过 Envelope 剩余 Finding 容量时返回标准
  `ENTITY_MAPPING_BUDGET_EXCEEDED` 422，不截断或静默遗漏。
- 强类型 Java/Database/Evidence Bundle Adapter 不能在同一 Envelope 混装，且必须与 Repository/Database/按
  Source Type 派生的 Provider Type 相符；Entity Mapping Marker 只能附着于 Java 或 Database Evidence，不能借
  Provider 标签伪造 Context Completeness。

### Java/Spring POC

- `JavaSpringPocProvider` 只接收有界、仓库相对路径的 `.java` 文本，使用静态文本分析；Contract 把
  `execute_analyzed_code` 固定为 `false`，不调用 Java Compiler、构建工具、ClassLoader 或被分析代码。
- Route 只从显式 `@Controller`/`@RestController` 类型或其本地接口 Contract 生成，不再按文件名猜测 Controller；
  `RequestMethod` 覆盖 GET/HEAD/POST/PUT/PATCH/DELETE/OPTIONS/TRACE，避免合法 Mapping 被静默遗漏。
- Mapping 与 Kafka Topic 中的 Spring `${...}` Placeholder/`#{...}` SpEL 不会被当作确定性运行值；无法静态解析时
  删除对应 Route/Topic Claim，产生显式 Incomplete Warning 并把 Submission 标为非确定性。
- JPA `@Table`/`@Column` 的本地 `static final String`、接口常量和限定常量引用复用安全常量解析；无法解析的显式
  名称不回退猜测 Table/Column，而是停止相应绑定并产生 Incomplete Warning。
- 转换后的 External Finding ID 在超长时保留有界可读前缀并附加 SHA-256 后缀；允许的 160 字符 Java Claim ID
  即使只在尾部不同也不会因 `java-` 前缀与截断发生碰撞。
- Controller 方法签名中的 `throws` 声明与方法体中的显式 `throw new` 都转换为 Exception Evidence，不因
  方法体截取边界遗漏已声明异常。
- CI Golden 使用 `small-spring-v1` 固定 Fixture，覆盖两个 Controller Route、Request/Response DTO Field 与
  Service Call。
- 完整 Golden Target 使用本地 sibling RuoYi revision
  `3b3941abeb5402297e5b4de82a30e6471c2239f3`，只读分析 SysUser Controller、Mapper 与 Entity 三个固定文件，
  验证 Route → DTO/Validation → Service → Mapper/Entity → Table Claim 链。RuoYi 不作为 CI 必需输入，避免阻断
  External Evidence 主路径。

## 3. 安全与正确性边界

- Java/DB Submission、转换后的 External Envelope 与 Context 初始输入继续执行 Secret、Credential、Token、
  Cookie、连接串、PEM、Email、Phone、Card 与高熵值检查。Enum/Observed Distribution 的标量值额外按 PII
  路径检查；Masked Example 除必须包含 `***` 外，残余内容也必须通过同一标量 PII 检查，不能夹带完整 Phone/Card。
- Source、Subject 与 Finding 始终作为 `untrusted_data`；适配器不解释 Prompt Instruction，不执行 Java、SQL、
  Shell 或任意网络访问。
- DB Evidence 仅用于设计候选；不建立数据库连接，不接收原始数据行，不改变既有 Runtime DB Read Oracle。
- DB 数值分布与 Enum 合同只接受有限浮点数，`NaN`/`Infinity` 在专用 Submission 与通用 External
  Evidence Envelope 两层边界都被拒绝，避免非标准 JSON 进入 PostgreSQL JSON 字段。
- Java Enum State、DB Enum Values 与 Observed Distribution Enum Candidates 在专用与通用 Envelope 两层边界
  复用同一标量敏感值检查；Phone/Card/Credential 等未脱敏值返回标准 422，错误正文不回显原值。
- Ingest 在锁定当前 Context Revision 后基于 Existing + New Evidence 计算歧义，避免在并发写入前静默遗漏冲突。
  Revision、Evidence Item 与 Fingerprint 继续使用 S49 的不可变约束。
- API Router 只做请求/响应适配；转换和候选规则在纯 Domain，授权、事务与 Revision 写入在 Application Service。

## 4. S52 Exit Criteria

| 条件                         | 当前状态  | 证据                                                     |
| ---------------------------- | --------- | -------------------------------------------------------- |
| Java Evidence 可进入 Context | 本地 Pass | API/Service 回归与隔离 Compose Playwright                |
| DB Evidence 可进入 Context   | 本地 Pass | API/Service 回归与隔离 Compose Playwright                |
| Entity Candidate 可追溯      | 本地 Pass | Candidate Evidence Ref 与稳定 Inspect 回归               |
| Conflict 可见且不静默选择    | 本地 Pass | Mapping Conflict + Context `conflicted` 端到端回归       |
| 无 Secret / PII              | 本地 Pass | 契约拒绝、标准错误 Envelope、安全扫描与 Compose 日志审计 |
| RuoYi POC                    | 本地 Pass | 固定 Revision/三个固定文件的静态 POC 回归                |

## 5. Intentionally Out of Scope / Blocked

### Intentionally Out of Scope

- 主动发现、认证或连接任意外部 Code/Database MCP Server。
- 完整 Java Compiler、完整语义索引、执行目标仓库代码或把 Built-in Java Provider 声称为生产能力。
- 数据库写 SQL、运行时 DB 验证替换、原始 Row/PII 采集。
- 自动选择或自动确认 Entity Candidate；用户确认后的持久化规则属于后续设计链路。
- S53 Data Recipe/Cross-API Oracle/DB Read Oracle、S54 Cleanup Runtime、S55 Sandbox Preview、S56 RC。

### Blocked

- 当前无已知本地实现阻断。PR 精确头检查、Review、普通 Merge 与 Main Push Gate 尚未完成。
- S52 Evidence Closure 合并且其 Main Push Required Gate 成功前，不进入 S53。

## 6. Validation 与 Evidence

### 已完成的测试先行证据

- 首次运行 `tests/test_s52_evidence_adapters.py` 在收集阶段以
  `ModuleNotFoundError: app.domain.evidence_adapters` 失败，确认测试先于实现。
- 首次运行 `tests/test_s52_evidence_adapter_api.py` 的三个用例均以专用 Endpoint `404` 失败，确认应用层测试先于
  API/Service 实现。
- 当前 S52 Domain + API、S49/S51 兼容、MCP Golden/SDK 与 S46 MCP Red Team 定向回归均已通过。

### 本地 Required Checks

| 范围                    | 命令                             | 结果                                                          |
| ----------------------- | -------------------------------- | ------------------------------------------------------------- |
| Backend Format          | `uv run ruff format --check .`   | Pass；465 files already formatted                             |
| Backend Lint            | `uv run ruff check .`            | Pass                                                          |
| Backend Types           | `uv run mypy app`                | Pass；337 source files                                        |
| Backend Tests           | `uv run pytest`                  | Pass；847 passed、4 skipped、总覆盖率 90.74%                  |
| Backend Security Lint   | `uv run ruff check --select S .` | Pass                                                          |
| Frontend Format         | `pnpm format:check`              | Pass                                                          |
| Frontend Lint/Types     | `pnpm lint`                      | Pass；ESLint 与 TypeScript                                    |
| Frontend Tests          | `pnpm test:coverage`             | Pass；57 files、222 tests；S/B/F/L = 86.23/80.12/85.44/88.48% |
| Frontend Build          | `pnpm build`                     | Pass                                                          |
| Python Dependency Audit | `uv run pip-audit`               | Pass；无已知漏洞，非 PyPI 项目包按工具约定跳过                |
| Node Dependency Audit   | `pnpm audit --audit-level high`  | Pass；无已知漏洞                                              |

### Compose / Playwright

- 使用 `flowtest-s52-local` Compose Project、`compose.yaml` 与 `deploy/s47/compose.yaml` 启动隔离完整栈；
  UI/API/Mock Target 仅绑定 `127.0.0.1:33052/38052/38053`，15 个服务全部 Healthy。
- `FLOWTEST_E2E_BASE_URL=http://localhost:33052 pnpm exec playwright test --project=chromium
e2e/s52-evidence-adapters.spec.ts`：Setup 与 S52 用例共 2 passed。真实路径覆盖创建 Context、Java Evidence、
  DB Evidence、Mapping Inspect、写 SQL 拒绝、第二张表造成歧义，以及 Context `conflicted` 与所有候选保持
  `proposed`。
- Review 8 语义修复后的 E2E Fixture 使用独立全新 `flowtest-s52-local` Project 与数据卷复验：Setup `1 passed`，
  S52 定向 Playwright `1 passed`；临时容器、网络与专用卷已删除，既有 Compose 卷未删除。
- 日志审计：Traceback、Unhandled Exception、测试危险输入 `DROP TABLE orders`、Email 地址均为 0；
  Authorization/Password/Secret 关键词只来自 Redpanda 配置项名称，5xx 数字只来自 Redpanda/Redis 基础设施
  日志，不是 HTTP 失败或敏感值泄漏。
- 验收后只删除 `flowtest-s52-local` 的容器、网络与数据卷；用户既有 `flowtest-compact`、`flowtest-ruoyi`、
  `flowtest-v5-compact` 仍分别保持 6 / 2 / 6 个运行服务。

### 首轮远端验证与 Review

- Draft PR：[#58](https://github.com/a3384379/FlowTest/pull/58)，Base
  `b6c281a832ec63e94433e0f322b30b6e342098c1`，首轮 Head
  `73dc0850e80dea443d000cd2a5ead0dadac469c7`。
- 首轮精确 Head CI 全绿：Backend `33175484561`、Frontend `33175484456`、Compose `33175484631`、
  Required Gate `33175484500`、Security `33175484502`、Windows `33175484558`、Upgrade `33175484451`。
- Codex Review 在 `73dc0850e8` 提出 1 个 P1 与 3 个 P2：外部结构化数据任意字典、DB 状态置信度/确定性丢失、
  DTO Field 跨 Operation 假冲突、Candidate Budget 在去重前误报。四项均在 `06a3e2c33c` 修复，对应 Review Thread
  已回复并关闭。
- 第二轮 Codex Review 在 `06a3e2c33c` 提出 1 个 P1 与 2 个 P2：DB Distribution 的非有限浮点数可导致
  PostgreSQL JSON 写入 500；持久化后的有效 Evidence 可靠性在 Mapping 重建时丢失；DB 可靠性未约束
  Operation/Entity 与 Field/Column 候选。三项均已修复，增加专用 Contract、Domain 与 API 回归；本地全量后端与
  安全门禁全绿；修复 `e91303cbfb` 已推送，对应 Thread 已回复并关闭。
- 第三轮 Codex Review 在 `e91303cbfb` 提出 4 个 P2：通用 Evidence 入口可绕过 Mapping Conflict 合成；
  Entity 非确定性未进入 Operation Mapping；下游 Field/State 候选丢失 Operation→Table 关联可靠性；
  Java 方法签名 `throws` 未提取。四项均在 `185d08d1cc` 修复并新增直接 Domain/API 回归，对应 Thread 已回复并关闭。
- 第四轮 Codex Review 在 `185d08d1cc` 提出 3 个 P2：满 100 Findings 时可能无空间持久化新冲突标记；
  非 Conflict 语义的伪 Marker 可抑制真实冲突合成；`table://public.orders` 点号 Schema 限定形式未匹配。
  三项均在 `5eea6ee53b` 修复并新增 Contract/Domain/API 直接回归，对应 Thread 已回复并关闭。
- 第五轮 Codex Review 在 `5eea6ee53b` 提出 2 个 P2：Java `table_column` 显式声明未参与 Field/Column
  候选及可靠性组合；同一 Operation 的多个 Enum State Field 共用 Source 且 DB State 相关未按 Field 隔离。
  两项均在 `24f91b0ecb` 修复，并新增不同命名显式列映射与双独立状态字段的直接 Domain 回归，对应 Thread
  已回复并关闭。
- 第六轮 Codex Review 在 `24f91b0ecb` 提出 1 个 P1 与 2 个 P2：通用 Envelope 的 Java/DB Enum 标量可绕过
  Phone/Card 检查；Route fallback 可选中已绑定其他 Operation 的 Entity；强类型 Adapter 未绑定 Provider Type，
  可伪造 Completeness。三项均在 `e926f07f4a` 的合同/Domain 边界修复，新增 Contract/Domain/API 直接回归，
  对应两个 Thread 已回复并关闭；Provider/Adapter Review Body 也已通过 PR Comment 回应。
- 第七轮 Codex Review 在 `e926f07f4a` 提出 1 个 P1 与 2 个 P2：Masked Example 只检查 `***`，仍可夹带完整
  Phone/Card；Java Claim 生成 External Finding ID 时直接截断可碰撞；DB Boolean State 使用 Python 大小写文本，
  与 Java JSON 风格值产生假冲突。三项均在 `9cbcd89f6d` 修复，专用与通用 API 的标准
  422/Trace ID/不回显敏感值、超长 ID 唯一性及 Boolean State 佐证均有直接回归，对应三个 Thread 已回复并关闭。
- 第八轮 Codex Review 在 `9cbcd89f6d` 提出 3 个 P2：显式 Operation Entity 存在时仍启用 Route/Table 启发式；
  无 Operation→Entity 候选时可吸收其他 Operation 的 `table_column`；DB Table Finding 未进入 Mapping Derivation。
  三项均在 `d02f44e1ff` 修复，新增显式 Entity 禁止假后缀表、跨 Operation Column/DB Table 隔离、Table-only
  Domain 与通用 API 可追溯映射回归；三个 Thread 已回复并关闭，第九轮 Codex Review 无新增问题。
- `d02f44e1ff` 的 Full Compose 发现 E2E 歧义 Fixture 仍依赖已移除的 Route 后缀假冲突；Fixture 已改为为同一
  Operation 显式声明 `ArchivedOrder→public.archived_orders`，使歧义验证与新的权威 Entity 语义一致；独立全新
  Compose 栈的 Setup 与 S52 定向 Playwright 均通过。
- 后续复审继续补齐 Java Collection Request DTO、Fully-qualified Kafka Annotation、Singleton Distribution、
  Controller Interface Mapping、Prefix/Overload、Java String Decode、Response Wrapper、Kafka Producer Topic、
  Evidence Provider Provenance、Standalone `0047` Head 与真实 Downgrade 回归。
- 最新复审指出集合容器 Overload 绑定、接口继承 Route、Mapping 常量、Framework 注入参数和迁移文档五项边界；
  当前实现已保留完整参数类型签名、递归解析本地接口继承、解析本地常量并对未知表达式显式标记分析不完整、排除
  Transport/Injected 参数，同时把本文件与 Migration Head 更新到 `20260829_0047`。五项均有直接回归。
- 下一轮复审指出文件名回退会把普通类误报为 Controller，以及显式 HEAD Mapping 会被遗漏；当前实现改为只接收
  明确 Spring Controller Annotation，并完整支持 Spring `RequestMethod` 的八种方法，含 HEAD/OPTIONS/TRACE 回归。
- 随后复审指出 Spring Mapping/Kafka Placeholder 可能被误报为字面运行值，以及 JPA Table 常量会错误回退类名；
  当前实现统一拒绝未解析 Placeholder/SpEL、为 Kafka 与 Mapping 产生不完整告警，并解析 JPA Table/Column 常量；
  未解析的显式 JPA 名称不再生成猜测绑定。对应常量、占位符和停止回退路径均有直接回归。

### 待完成

- 最新修复 Head 的精确 CI、Codex Review、普通 Merge、精确 Main Push 与 Evidence Closure。

## 7. Remote Evidence

- 当前已取得首轮实现 Head 的全绿 CI 与 Codex Review；它们只证明
  `73dc0850e80dea443d000cd2a5ead0dadac469c7`，不替代 Review 修复后 Head 的证据。
- 最终实现 Head、对应 Required Check Run、最终 Codex Review、普通 Merge SHA 与 Main Push Gate 将在后续精确
  取证完成后补录。
- 禁止 Admin Merge、Force Push、Ruleset Bypass、跳过 Required Check 或直接推送 Main。
