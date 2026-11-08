# 自测体系开发验证记录

本文保存首次 S1/S2 的历史验收，以下“未实施”等状态仅对应该轮。继续开发后的产品链路见[系统自测工作台](product-workspace.md)，当前逐项状态以[验收矩阵](acceptance-matrix.md)及后续构建回执为准。

持续开发的检查、构建与未运行边界见[当前验证记录](current-validation.md)。

记录日期：2026-10-23。本文区分已取得的本地检查、真实隔离运行和尚未执行的验收。
完整需求边界见[实施基线](implementation-baseline.md)，入口见[固定回归](fixed-baseline.md)、
[设计编译](design-compilation.md)和[生命周期生成](lifecycle-harness.md)。

## 修改文件与复用入口

| 范围                     | 主要文件与结果                                                                                                                                                                                                                                                                                |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 固定 Design 编译         | [Domain 编译器](../../backend/app/domain/test_design_compilation.py)、[共享 lowering](../../backend/app/domain/test_design_lowering.py)、[授权服务](../../backend/app/services/test_design_compilation.py)；复用已有原生图与 FlowSpec 转换                                                    |
| MCP 与版本来源           | [MCP server](../../backend/app/mcp/server.py)、[生成服务](../../backend/app/services/test_engineering.py)、[IntegrationPlan](../../backend/app/services/integration_plans.py)、[导入回执](../../backend/app/services/mcp_contract_import.py)；同步 client、DTO、目录及五个 Skill 契约 fixture |
| 原生执行修复             | [运行时路径绑定](../../backend/app/services/workflow_runtime.py)、[快照绑定](../../backend/app/services/workflow_snapshots.py)、[原子计划仓储](../../backend/app/repositories/tasking.py)、[计划协调器](../../backend/app/services/test_plan_runner.py)；保留原执行链                         |
| 有界只读证据             | [CI 路由](../../backend/app/api/v1/endpoints/ci_evidence.py)、[证据服务](../../backend/app/services/execution_evidence.py)、[DTO](../../backend/app/schemas/execution_evidence.py)；新增 `read:execution`                                                                                     |
| Harness、Observer 与隔离 | [scripts/selftest](../../scripts/selftest/)、[部署](../../deploy/selftest/)、[Mock 业务及管理入口](../../mock-target/app/selftest.py)；独立批次 journal、黄金规则、双 JUnit 与失败清理                                                                                                        |
| 固定包与生成任务         | [selftest/packs](../../selftest/packs/)、[严格 Schema](../../selftest/schemas/)；固定基线和现场生成分开计数                                                                                                                                                                                   |
| 前端兼容与权限           | [组织治理页](../../frontend/src/pages/OrganizationGovernancePage.tsx)、[生成服务 DTO](../../frontend/src/features/test-engineering/test-engineering-service.ts)及命名回归；补齐 scope，未新增自测页面                                                                                         |
| 回归与说明               | 新增及扩展后端、Mock、前端行为测试；本目录五份说明与 [selftest README](../../selftest/README.md)                                                                                                                                                                                              |

完整 120 个修改文件的清单另留存在 `output/selftest-validation-20261023/changed-files.txt`；工作区保持未提交。没有修改 CI 治理工作流、依赖锁文件或数据库模型/迁移。

## 源码与环境绑定

| 项目         | 已核实事实                                                                                                               |
| ------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Git 基线     | `70e4b513e734c2c47053ecc314db0bbd092f16db`；本次开发包含未提交修改，Git HEAD 本身不代表最终镜像内容                      |
| 工作区       | `/Users/sqz/.codex/worktrees/mcp-native-selftest/FlowTest`                                                               |
| 隔离栈目录   | `/private/tmp/flowtest-selftest-20261023`                                                                                |
| Compose 项目 | `flowtest-selftest-2743191d381d`；只管理该项目的 ownership/nonce 所属资源                                                |
| 部署形态     | 验收时使用 Standalone A/B，独立数据库卷、签名和加密密钥；Mock 与 Observer 分开监听；结束后已清理临时栈                   |
| 网络         | execution 为独立 internal 子网；management 隔离 A；runner/target/observer 各有单独 control 网，仅在 `127.0.0.1` 发布端口 |
| 实际绑定     | `stack.json`、`build-receipt.json`；冻结源码/依赖/镜像摘要及容器、网络、卷身份，最终 refresh 后以该文件为准              |
| 初始化       | bootstrap 已经通过公开 API 完成；安装身份保存在 `installation.json`，私密凭据不进入本记录、mapping 或批次报告            |
| 本地信任级别 | `local_untrusted`；没有签发 `trusted_ci` 或远程 Required Gate                                                            |

启动与 refresh 会重新读取 Docker 身份，核对五张网络的精确成员集合、loopback 端口、独立 A/B 卷和凭据。
源码变更必须实际 build 并重建本项目容器，不能修改旧绑定中的摘要冒充已运行新镜像。

最后一次已核实 refresh 为 `resume-5`，以下值与 `stack.json`、`build-receipt.json` 和成功批次的构建绑定一致：

- source digest：`c386cb1626750a23f4efd0d26c19ee0fffa74843d5e084bf2589720d4d487e6e`。
- dependency digest：`7a17de5b6da8f45f0254c670cefd0dd3d5fd88cf16b2017744b3e57f199a5eec`。
- A/B candidate image：`sha256:68f46c9c2bf839da2d022896299504d04bf6cd941fd3a9e2d35fd70499783c9f`。
- fixture image：`sha256:ae35ada698a48552202953cbe63f6cefe6d257508856b0137a06728157b556fb`；批次中 fixture digest 使用去掉 `sha256:` 的纯十六进制值。
- `build-resume-5.log`、`start-resume-5.log`、`resume-5.json` 和 `/tmp/flowtest-selftest-refresh-5.log` 保留实际 build/recreate 记录。
- 成功批次后再次执行的 `verify_binding` 与三健康检查保存在 `refresh-5-validation.json`：五张网络成员集合通过，runner/target/observer 健康均为 HTTP 200。
- 旧 `refresh-validation.json` 仍保留 `resume-4` 的历史值，不能用它证明 refresh 5；新旧回执未互相覆盖。

镜像健康与绑定验证不单独证明业务通过。下方真实批次各自保存运行前 manifest、来源与独立核验收据；核验器摘要也按各批次分别记录。

## 已通过的定向验证

| 验证                                                       | 实际结果                                                                                             | 本机日志或源码                                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 独立 Observer、隔离 Harness、生命周期采证、CI 只读证据 API | `make test-backend-targeted`，94 个测试通过                                                          | `/tmp/flowtest-selftest-observer-final.log`；四个命名测试文件见下方命令                                                                                                                                                                                                        |
| Observer/Harness/collector 类型                            | 命名脚本 mypy 通过，使用 backend 的配置和 `MYPYPATH=backend`                                         | [独立契约](../../scripts/selftest/contracts.py)、[验证器](../../scripts/selftest/verify.py)、[来源验证](../../scripts/selftest/verify_generation_provenance.py)、[采证](../../scripts/selftest/collect_lifecycle_evidence.py)、[启动器](../../scripts/selftest/local_stack.py) |
| 改动格式与静态检查                                         | 上述命名脚本及对应测试 Ruff format/check 通过                                                        | 使用 `backend/pyproject.toml`；后端测试按 backend 工作目录检查                                                                                                                                                                                                                 |
| JSON Schema                                                | manifest、evidence、generation-provenance、verification 均通过 Draft 2020-12 schema 检查             | [schemas](../../selftest/schemas/)；由严格冻结模型生成                                                                                                                                                                                                                         |
| 隔离栈健康和绑定                                           | 已实际 build/start/refresh；A/B `/api/v1/live` 和 Observer `/health` 均返回 200，Docker 绑定核验通过 | 最后已核实 `resume-5`，对应 build/start 与 `refresh-5-validation.json` 见栈目录                                                                                                                                                                                                |

94 个自动化测试是本次命名测试文件的数量，不等于需求矩阵中的 94 项验收全部通过。
这些测试包含非法/缺失/重复集合、旧回执、失败节点或错误码替换、早期 attempt 被掩盖、完整来源被删减、
Suite/计划快照被替换、业务后置查询过期或跨项目、非完整证据、外来容器混入，以及只读授权和秘密字段不导出。

已执行命令：

```sh
make test-backend-targeted TARGETS='["tests/test_selftest_verification.py","tests/test_selftest_harness.py","tests/test_selftest_lifecycle_evidence.py","tests/test_ci_execution_evidence.py"]'
```

其他编译、调度、MCP、固定包定向结果按各自日志保留，不把不同轮次的通过相加成当前完整门禁。

历史全量 `make check` 曾通过，日志为 `/tmp/flowtest-selftest-make-check-final.log`：后端 Ruff/format、mypy 452 文件、2140 passed / 14 skipped，覆盖率 91.28%；前端 format/lint、189 个测试文件 / 1450 个测试通过、V8 statements 86.63% / lines 89.20%，build 成功。**该次全量通过早于最新少量产品及 H/O 变更，不是当前工作区最终完整检查，也不是当前 HEAD 的远程门禁。** 最新完整本地检查结果见下方最终记录。

## 已完成的真实隔离运行

下列运行均为 Standalone 本地隔离栈、`local_untrusted`。审核使用专用 reviewer 经现有审核 API 执行的受控 `review_mode=ci_fixture`，不是浏览器人工审核验收，也不代表真实 Host/Skill/LLM 已执行。

所有已登记成功轮次的 `evidence_integrity=complete`、批次及场景 `cleanup_status=completed`，每个场景只有 1 次正式 execution attempt。核验结论按冻结范围给出，不将后续重跑覆盖前面失败尝试，也不把所选集通过写成完整 94 项需求验收通过。

| 目录及 round                                                      | batch_key                   | 实际冻结范围                                              | 实际独立结果                      | 原始 / 核验 JUnit                          |
| ----------------------------------------------------------------- | --------------------------- | --------------------------------------------------------- | --------------------------------- | ------------------------------------------ |
| `/private/tmp/flowtest-selftest-canary-attempt-6/round-1`         | `mcp-e0f40cae49ccad663fae`  | `diagnostic_subset`；expected=required=`ST-MCP-025/026`   | 2 matched；verdict passed；exit 0 | 2 tests / 1 failure；2 tests / 0 failures  |
| `/private/tmp/flowtest-selftest-mcp-core-stdio-attempt-7/round-1` | `mcp-bc0ec1894c8238039dfe`  | `selected_suites`；expected=required=`ST-MCP-023/025/026` | 3 matched；verdict passed；exit 0 | 3 tests / 1 failure；3 tests / 0 failures  |
| `/private/tmp/flowtest-selftest-mcp-core-stdio-attempt-7/round-2` | `mcp-0923315fd3792a4f07ee`  | 同上，独立新批次                                          | 3 matched；verdict passed；exit 0 | 3 tests / 1 failure；3 tests / 0 failures  |
| `/private/tmp/flowtest-selftest-mcp-core-http-attempt-8/round-1`  | `mcp-795100fb347b2b96cc4a`  | `selected_suites`；expected=required=`ST-MCP-023/025/026` | 3 matched；verdict passed；exit 0 | 3 tests / 1 failure；3 tests / 0 failures  |
| `/private/tmp/flowtest-selftest-fixed-core-attempt-10/round-1`    | `core-d5c908a2e2c91da9ca4f` | `full_pack`；当前最小 `core-v1` 的 8 场景                 | 8 matched；verdict passed；exit 0 | 8 tests / 2 failures；8 tests / 0 failures |

每行的 `manifest.json`、`evidence.json`、`verification.json`、`execution.junit.xml`、`verification.junit.xml` 构成相互对应的证据。命令 stdout 位于同名目录旁的 `.log`；成功 stdout 中也保留该 batch_key、verification_scope 与 exit_code。`full_pack` 仅表示这次固定 core-v1 八场景的完整范围，不是需求矩阵 94 项。

### 真实 MCP 协议及来源绑定

MCP 成功批次均为 `deterministic_mcp`，SDK `2.2.0`、协议 `2026-07-28`，实际 `tools/list` 目录摘要为 `c50808971cf44433b6511829640fb18c825fba16d54b22deb8d8f8b55c099d93`。每轮 `mcp-catalog.json` 保存实际发现结果，`mcp-calls/` 保存实际调用回执；没有用 REST fixture 替代 MCP transport。

- canary attempt 6：stdio，来源链含 18 个成功工具调用回执。
- core stdio attempt 7：round 1 / round 2 分别含 41 / 40 个成功工具调用回执。
- core HTTP attempt 8：独立 streamable HTTP MCP 监听，含 40 个成功工具调用回执；不能用 stdio 结果替代该轮 HTTP 证据。
- MCP pack digest：`9e1e156018118c4874f00751684f13b419f6f75188dab47f08b9e7817e09ce67`。
- canary subset policy digest：`94685c38d3a0c346654c04f5408aac8d12f3c628497b03bccdd93625162ce4d3`；三场景 selected_suites policy digest：`c393d622933efb1060583ddb13997bf8556ec0ebcdf82fb71879e527a5071c9a`。
- canary 核验器摘要：`bbfe55e360db9c0ad76dd537df5612858c552f7d40cad3f7806bd9409a2cba01`；core stdio/HTTP 核验器摘要：`b6f8ca75f7cfa3acdbd35f957277b2af996cdf415221b66be858f2bbee65d165`。这些是各轮实际身份，不用后一个摘要回填早期轮次。

`ST-MCP-023` 真实生成并执行 B 的 login/create/list/patch/delete 环境生命周期。其五个状态码黄金值为 200/201/200/200/204；create/patch 的本批合成名称以及运行结束后创建/更新名称均不存在的独立查询同时通过。具体契约、Design、Integration Plan、编译、审核物化、发布版、Suite/Plan 展开快照和执行引用分别保存在场景目录及来源证据中。

四个 MCP 成功轮次的负 canary 均保留原始 `failed + WORKFLOW_ASSERTION_FAILED`，精确失败位置为 `assert_schema_1` / `main`，独立核验为 matched；每项只有一次目标请求和一次正式执行 attempt。正 canary 均为原始 passed + matched。原始 JUnit 每轮的一个 failure 是实际负例结果，不会被核验 JUnit 的零失败覆盖。

### stdio 连续两轮的资产独立与源复用

attempt 7 两轮复用了同一个已初始化 A/B 绑定（`installation-binding.json` 的 reused=true），但生成调用、提案、Workflow、Case、Suite、Plan 和 execution 均属于各自本轮。下列已发布 Workflow/Case 的实际版本号均为 1，WorkflowVersion ID 和内容指纹也分别保存在各轮 `reviewed-workflow.json`；编号同为 1 不表示同一对象。

| 场景       | round 1：Workflow / Case ID                                                     | round 2：Workflow / Case ID                                                     |
| ---------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| ST-MCP-023 | `dd256aba-ec12-40f0-b422-e2041a671a8d` / `f4a554bd-f6bf-42e5-bfc8-7d5ee523cdf9` | `18c61631-1319-4dbc-863b-b1cf063d2e59` / `e82e68dc-c2ed-4625-9741-0d9dcfdcda66` |
| ST-MCP-025 | `7c034b36-68e7-4849-8b43-9b0eb2bf1370` / `73705a28-f4da-41ef-99f2-aef90bdb3bf2` | `9f475c73-ec5c-455b-8c7e-229bf0b0e554` / `74ee8399-62c2-47ee-ad47-032180709bf2` |
| ST-MCP-026 | `05bc0e96-3146-4d21-b83f-2b3864f0a9d3` / `f9b85103-99d0-48ac-96c2-a6091fc34897` | `a02e03ec-d0a2-4f98-9105-5ac8d1b932e4` / `c5399a9e-818c-4740-a826-9824a81003d1` |

- round 1 Suite：`aff39b4f-ad09-4754-a9b3-ce1da5d3490d` v1；Plan：`7ce400b8-6003-4145-9b43-76c4bd2307b0`；PlanRun：`3484be23-ff53-469e-bd6a-784c9d877233`。
- round 2 Suite：`6d4838ed-6613-4488-9cef-b9b315505fd8` v1；Plan：`5d845c35-a2ab-467a-8a2d-bcb8e920db3a`；PlanRun：`fdf05cb8-6ff9-403e-816b-1cf44fd68bd7`。
- 两轮各三项的 FlowSpec proposal ID、Case change-set ID、Case item ID、WorkflowVersion ID 和 execution ID 集合分别不相交；发布引用、计划展开快照与全部尝试对应本轮对象，未使用旧执行抵扣本轮结果。
- 生命周期 `source_reused` 从 round 1 的 false 变为 round 2 的 true；五个源 API ID、固定版本 1 和契约指纹完全相同。这是合法的导入去重，不要求源契约每轮新建。
- 每轮仍重新调用 MCP 生成 Design。相同冻结源与确定性策略会得到相同的五个 Design 指纹及组合 Design 指纹 `aa430ea89c6edc5c3614e713c4e9ade7363a4f9272e48f6eac3f00df0718b25d`；不能把指纹相同误判成“本轮没有生成”，也不能凭它虚构新的持久 Design 资产 ID。
- canary 路径含本轮 batch_key，所以两轮 canary 的源 API ID、Design 指纹与发布对象均不同；原始契约回执和 `generated-asset.json` 保留该区别。

### 固定 core-v1 的真实运行

attempt 10 的冻结集合为 echo-boundaries、business-failure、timeout、if、foreach、repeat、retry、poll，对应 `ST-CORE-*` 八项；expected=required=实际集合。pack digest 为 `93d772af7216b661586dd0f4714b49b295846d192c383d8c4cc2fff21164b9bf`，policy digest 为 `8c3bd2cc1cb00a34c5ac9e98006b1657564f6ce62ff8531c186c893564531a77`，核验器摘要为 `f22812935340e46dba1dbb6d81fdd86e877cd045fdc2df2472f84a024c11acdd`。

| 场景             | 原始执行 / 独立核验 | 独立 Mock 请求数与关键证据                                      |
| ---------------- | ------------------- | --------------------------------------------------------------- |
| echo-boundaries  | passed / matched    | 5；0、false、null、空串、中文及合成 Authorization header 存在性 |
| business-failure | failed / matched    | 1；`assert_business` / main / `WORKFLOW_ASSERTION_FAILED`       |
| timeout          | failed / matched    | 1；`request` / main / `NODE_TIMEOUT`                            |
| if               | passed / matched    | 1；仅 true 分支                                                 |
| foreach          | passed / matched    | 3；迭代 ordinal 0/1/2，完整一页、未截断                         |
| repeat           | passed / matched    | 2；迭代 ordinal 0/1，完整一页、未截断                           |
| retry            | passed / matched    | 2；503→200，计划层仍只有一次正式 execution attempt              |
| poll             | passed / matched    | 3；第三次满足固定条件，计划层没有补跑                           |

合计 18 个独立请求；全部场景 cleanup completed。原始 execution 的两个 failed 在 `execution.junit.xml` 保留，独立 `verification.junit.xml` 为 8 项零失败。该固定线验证原生导入/发布、Case/Suite 包映射、计划运行与控制流，不计作 MCP 生成验收。

### 独立资产证明与实际篡改 CLI

`/private/tmp/flowtest-selftest-acceptance-proof.json` 记录于 `2026-10-22T17:45:49.908853+00:00`，检查退出码 0，来源为 `local_untrusted`。它逐项确认 stdio 两轮的 Workflow、WorkflowVersion、Case 及全部 execution ID 集合分别互斥；第二轮生命周期 source_reused=true，且两轮本批合成名称均有独立观测。证明只覆盖已登记的本地 selected_suites 证据，不授予 trusted CI、真实宿主或正式发布结论。

以 HTTP attempt 8 的证据副本实际调用 `python -m scripts.selftest.verify --manifest ... --evidence ... --output-dir ...`，完整 argv、退出码及输入 SHA-256 均保存在该 proof；两份实际 CLI stdout/stderr 与核验输出保存在 `/private/tmp/flowtest-selftest-acceptance-tamper-e1_hnql3`：

| 副本目录                       | 实际修改                                                                           | CLI / verdict                       | 唯一 finding                      |
| ------------------------------ | ---------------------------------------------------------------------------------- | ----------------------------------- | --------------------------------- |
| `missing_optional_mcp_receipt` | 从 ST-MCP-023 来源调用序列删除一次 `flowtest.inspect_contract` 回执；不改 manifest | exit 1 / failed；该场景 mismatched  | `FROZEN_MCP_RECEIPT_SET_MISMATCH` |
| `missing_scenario`             | 从 evidence 删除 ST-MCP-023；不改 expected/required 集合                           | exit 2 / blocked；该场景 incomplete | `REQUIRED_SCENARIO_MISSING`       |

两次 CLI 检查时批次均未过期，其他两场景仍 matched，失败由对应篡改触发，而非 deadline 或附带错误。两份副本的 manifest 和原始 execution JUnit 保持原样；proof 列出的三组原始轮次共 15 个输入文件 SHA-256 均未改变。原成功证据没有被改写，篡改输出也没有覆盖原 `verification.json`。这两项是实际负向核验，不等于全部故障注入矩阵已经完成。

## 异常路径清理与 Mock 路由错误修复

`scripts/selftest/cleanup.py` 的 `RoundCleanup` 由 MCP 主运行器和固定基准入口共用。清理不以父运行摘要或单个成功响应推断全部任务已经停止：

1. 正式 launch 前先持久化计划 ID、项目、完整目标集合和 launch intent，拿到真实 run ID 后再补回执。launch 结果未知时保持 needs_review，不猜测 run ID，也不开始删除业务资源或 Mock namespace。
2. 读取计划/子项和**全部 execution attempts**，核对项目、计划、运行项、执行身份、完整集合及终态；需要停止时走真实公开 cancel API，然后继续只读查询确认停止。取消响应丢失可由后续读取收敛，不重复发取消写入；截止时仍未收敛不能成功。
3. 停止确认后，由独立 B viewer 读取本批环境，H 的受限 writer 按已登记真实 ID 回收。删除前再次核对项目、owner、精确名称和带时区的创建时间窗口，并重新检查 ID/名称/资源记录未变化；删除后查询确认资源已不存在。
4. 最后清理已经登记的本批 Mock scenario namespace。成功路径保留完成回执，重复 finally/finish 返回原回执，不重复发出删除。清理过程、意图、原因和完成状态保存在 `cleanup.json`。

未知 launch、取消未收敛、无时区时间、owner/ID 漂移、资源归属不明、未知 DELETE 结果或删除未确认均记录 failed/needs_review，不能标 completed 或给出成功核验。不会按名称前缀批量删除无关资源，也不会以新的幂等键盲目重试未知结果；正常成功流程已确认的业务清理不会再次删除。

| 验证               | 实际结果                                                                                                                                      | 证据                                                                       |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 修复前异常路径表征 | MCP 配置异常后已登记 fixture 未删除，独立测试实际失败                                                                                         | `/tmp/flowtest-selftest-cleanup-repro.log`                                 |
| 清理及关联回归     | 121 passed，7.03s；覆盖未知 launch、取消收敛、全部 attempts、归属/时间/ID 漂移、未知 DELETE、成功不重复清理等                                 | `/tmp/flowtest-selftest-cleanup-final-tests.log`                           |
| Mock 路由表征      | 修复前 business/observer 两项失败；404 响应缺标准 error envelope                                                                              | `/tmp/flowtest-selftest-fixture-routing-before.log`                        |
| Mock 修复后行为    | 18 passed，0.41s；两监听器 404/405 均使用标准 error envelope 与 trace ID，代码分别为 `FIXTURE_ROUTE_NOT_FOUND` / `FIXTURE_METHOD_NOT_ALLOWED` | `/tmp/flowtest-selftest-fixture-routing-after.log`                         |
| 本轮脚本静态检查   | mypy 19 个脚本通过；Ruff format/check 23 个文件通过                                                                                           | 主验证终端检查记录；未另存日志，不使用旧 3/18 文件 mypy 或旧 lint 日志替代 |

121 项回归的实际命令：

```sh
make test-backend-targeted TARGETS='["tests/test_selftest_cleanup.py","tests/test_selftest_fixed_baseline.py","tests/test_selftest_journey_contracts.py","tests/test_selftest_lifecycle_evidence.py","tests/test_selftest_verification.py"]'
```

静态检查在 backend 工作目录执行：

```sh
uv run ruff format --check ../scripts/selftest ../mock-target/app/selftest.py ../mock-target/app/selftest_contracts.py ../mock-target/app/selftest_journal.py ../mock-target/tests
uv run ruff check ../scripts/selftest ../mock-target/app/selftest.py ../mock-target/app/selftest_contracts.py ../mock-target/app/selftest_journal.py ../mock-target/tests
MYPYPATH=.. uv run mypy --explicit-package-bases ../scripts/selftest
```

Mock 路由修复后已重新 build/recreate 为 refresh 6。当前 `stack.json` 与 `build-receipt.json` 的源码摘要为 `269376ac7ca8eea75b96bfc7f29a0951bbc565f26d4d62e7eb4c28ce9b4230eb`，A/B 镜像为 `sha256:c5cf543ee8fd75cbac2450680793213b6a4b670aa72a6578c1242d82318f940c`，fixture 镜像为 `sha256:ad3f09edd079435d76b207273baa94f8389849d6900b9226b6632daa43ec3167`。`/private/tmp/flowtest-selftest-mcp-core-final-11/round-1` 的 manifest 使用这些镜像身份，已有 HTTP MCP 核验 passed / exit 0 / complete 记录；最终批次、完整检查与整栈清理已在后文登记。

上方 refresh 5 及 attempts 6–10 属于其各自历史构建，摘要保持原样。refresh 6 的结果不能回填成旧批次的运行身份；最终完整 `make check` 已另行执行并通过，记录见后文；本节定向通过不替代该检查。

## 最终构建的真实运行与清理

refresh 6 的实际身份见 `refresh-6-validation.json`，A/B readiness 与 Observer health 均为 200，五张网络的成员集合再次核实。以下运行使用最后的异常清理实现与 Mock 错误接口修复，所有命令实际退出 0；先前 refresh 5 的批次继续保留自己的身份。

| 最终输出目录（均位于 `/private/tmp`）       | 模式与轮次            | 实际结果                                                                          |
| ------------------------------------------- | --------------------- | --------------------------------------------------------------------------------- |
| `flowtest-selftest-mcp-core-final-11`       | Streamable HTTP，1 轮 | 三场景 selected_suites 全部 matched；负 canary 原始 failed                        |
| `flowtest-selftest-fixed-core-final-12`     | 固定 core-v1，1 轮    | 八场景、18 次请求；业务负例与超时原始 failed；全部 matched                        |
| `flowtest-selftest-mcp-core-final-stdio-13` | stdio，2 轮           | 每轮三场景全部 matched；两轮 Workflow、版本、Case、全部 Execution ID 集合分别互斥 |

最终 stdio 两轮均复用已固定的五个生命周期 API 契约，`source_reused=true`；每轮仍重新生成、审核发布并执行独立产物。三组 MCP 运行的新 cleanup 回执均 completed，正常 Plan 的 `cancel_requested=false`；两个 Mock namespace 已删除，B 名称 absence 完整，H 未额外删除正常业务已经清理的资源。原始 JUnit 每轮为三项一失败，独立 JUnit 三项零失败，原始失败没有被重写。

`/private/tmp/flowtest-selftest-final-acceptance-proof.json` 的检查实际退出 0，来源保持 `local_untrusted`。以最终 HTTP 批次的副本再次运行真实 verifier CLI，删一条 inspect 回执退出 1、唯一 finding 为 `FROZEN_MCP_RECEIPT_SET_MISMATCH`；删 ST-MCP-023 退出 2、唯一 finding 为 `REQUIRED_SCENARIO_MISSING`。两次检查在批次过期前完成，新输出在 `/private/tmp/flowtest-selftest-acceptance-tamper-zk9th922`，24 个原始输入 SHA 前后相同。

运行后先核实 ownership 和完整 binding，再执行本隔离栈的 `stop`：owned 容器、五张网络和三个卷均已移除，`private.env` 已删除。`cleanup-validation.json` 比较清理前后 81 个无关容器的 ID、名称及运行状态，完全一致；此结论仅描述清理前后容器清单，不推断其他应用数据状态。原工作区仍只保留原有 AGENTS、README 和 `.playwright/` 改动。

## 剩余验收与最终检查登记

| 项目                          | 当前登记状态                                                          | 最终必须记录                                                                         |
| ----------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 更多固定场景 / 完整 94 项矩阵 | 最小 core-v1 八项已完成；其余未验收                                   | 逐项场景、真实证据与未覆盖项；不能由本次八项推断                                     |
| 失败注入与证据篡改            | 实际删 inspect_contract 回执 / 删 ST-MCP-023 两项已登记；其他项待填写 | 其他原始状态/来源替换、坏目标及缺失证据组合的实际输入、非零退出码及 finding          |
| 当前工作区最终 `make check`   | 已完整通过，退出 0                                                    | 后端 2196 passed / 14 skipped，前端 189 文件 / 1450 passed；完整日志与源码摘要见下方 |
| 最终整栈清理                  | 场景及整栈清理均 completed                                            | `cleanup-validation.json`；owned 资源全部不存在，无关容器清单不变                    |

## 已保留的失败与修复边界

| 尝试                   | 已保留事实                                                                                                                                      | 处理及后续边界                                                                                         |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 初次 Docker start      | `start.log`：执行子网与既有 Docker 地址池重叠，Compose 非零退出                                                                                 | 改为读取实际 IPAM 后选择不重叠私有 `/24`；原日志未覆盖                                                 |
| resume 1               | 容器健康但 internal-only 网络下 loopback 发布端口未生效，绑定检查拒绝；`start-resume-1.log` 保留                                                | 分离三张 control 网，只 recreate 本 owned 容器，保留数据库卷；resume 2 实际绑定与健康验证通过          |
| stdio canary attempt 1 | `/private/tmp/flowtest-selftest-canary-attempt-1/failure.json`：`SELFTEST_MCP_STRUCTURED_RESULT_MISSING`                                        | 调用未提供工具要求的 `request: {}`；修正 Harness 后必须另起批次重跑，不能回写成功                      |
| stdio canary attempt 2 | `/private/tmp/flowtest-selftest-canary-attempt-2/failure.json`：`SELFTEST_REVIEW_DEFINITION_CHANGED`                                            | 严格审核比较发现 native definition 的规范化差异；保留阻断及实际 MCP 回执，修复产品输出后重新 build/run |
| MCP core attempt 3     | `/private/tmp/flowtest-selftest-mcp-core-attempt-3/failure.json`：`SELFTEST_CONTRACT_NOT_NEW_FOR_BATCH`                                         | 保留源契约去重与“每轮必须新建”假设冲突的阻断；后续两轮明确区分源复用与执行资产重新生成                 |
| stdio canary attempt 4 | `/private/tmp/flowtest-selftest-canary-attempt-4/failure.json`：`SELFTEST_CONTRACT_MAPPING_MISSING`                                             | 源映射未满足收集器要求，未进入成功分子；后续新轮次独立采证                                             |
| stdio canary attempt 5 | `/private/tmp/flowtest-selftest-canary-attempt-5/failure.json`：`SELFTEST_HTTP_409`                                                             | 记录实际 409 阻断；该 failure 文件未给出更细业务错误码，不以推测补写成功或覆盖旧结果                   |
| fixed core attempt 9   | `/private/tmp/flowtest-selftest-fixed-core-attempt-9/round-1/verification.json`：blocked / exit 2，`SELFTEST_HTTP_422_FIXTURE_VALIDATION_ERROR` | 根入口误传带 `sha256:` 前缀的 fixture digest；修正为纯 hex 后另建 attempt 10，旧 blocked 报告保留      |
| 调度边界表征           | `/private/tmp/flowtest-selftest-scheduler-boundaries.log` 保留修复前并发 claim、重复 complete、父 passed/子非终态失败                           | 相关最小修复和新增回归需在最终记录中列出；修复前失败日志不能作为最终通过证据                           |
| 首轮全量 `make check`  | `/private/tmp/flowtest-selftest-make-check.log`：后端 1 failed、2095 passed、14 skipped，覆盖率 91.24%；未到达完整前端通过                      | 当时失败项为 Mock 模块独立加载兼容性；修复后定向结果与最终全量重跑分别登记，不能把该轮写为全量通过     |

失败现场可用于定位问题，不能计入成功生成/执行分子。最终新轮次以自己的构建和回执判定，不能拿旧轮次内容补全。
本机 `/private/tmp` 日志只描述当前开发机证据，不是可移植或可信 CI 签名制品；交付时需另记录留存位置和摘要。

## 未执行与未完成的验收

- 真实 Host/Skill/LLM：`NOT_RUN / WAITING_FOR_HOST`。缺少已注册宿主、安装 Skill、provider 授权及明确模型预算；确定性 MCP 不能抵扣。
- Full/Compact、Windows Standalone、全部故障/profile/feature 组合：未取得本轮完整运行证据。
- S3 分层远程 CI 与真实宿主/LLM：未实施；本地双 JUnit 与确定性 MCP 结果不代表远程门禁或真实模型验收。
- S4 产品化持久层与 UI API：未实施；当前成功来源为本地 Harness 回执，不是已注册到产品后台的 binding/installation/batch 服务。
- S4 系统自测工作台、初始化抽屉、报告来源/核验 UI 与真实浏览器端到端：未实施。前端增量方案已只读梳理；组织治理 scope 选项同步不等于 S4 自测界面完成。
- 完整 94 项需求矩阵：未完成；固定八项和 MCP 三场景不能相加冒充全部需求验收。
- 当前提交的远程 PR Required Gate、合并后 CI、部署和正式发布验收：尚未取得本轮证据。
- 本轮完整本地 `make check` 已通过；当前远程门禁、跨部署形态和发布验收依然独立，不由本地结果推断。

生命周期的独立黄金值固定五个 B 接口的已知状态码、create/patch 响应中的本批合成 `name`，以及执行后本批创建/更新名称均不存在。
独立 A project viewer 通过已有 CurrentUser 执行明细读取已授权合成 capture，只在内存处理；落盘只含绑定批次、执行、API/节点和 `name` 的有界字段证据。
B 资源后置查询使用独立 B project viewer；两种 viewer 的 JWT 均仅在 Credentials 内存中，组织成员与项目只读身份由公开 API 创建和核实。
独立 Observer 同时核对完整的运行前冻结 MCP 回执序列，删除 coverage/inspect 等任何一项也不能通过。
全部 Schema Oracle 的映射、预期摘要和真实断言摘要会保留并交叉核对；动态 token/UUID/整段响应体没有被假定为固定黄金值。
当前 Observer 没有独立导出完整动态响应并重算所有 Schema 验证，摘要来源链不能表述成独立完整 Schema 语义验证。

## 本轮交付的阶段边界

本轮已取得 S1/S2 **核心纵向切片及其回归**的实际证据，不宣布 S1/S2 的所有场景 ID、全部 P0 变体或完整需求矩阵均已完成。真实 MCP 纵向使用 B 的环境资源：登录、创建环境、列出环境、修改环境、删除环境。项目本身没有 delete 接口，其他项目管理验收尚未覆盖，不能将环境生命周期结果扩展为完整项目 CRUD 验收。

当前 pack 尚无 ST-API-003 项目/目录生命周期、ST-API-004 原生引擎管理 API 版本、ST-API-006 多层 Header 覆盖、ST-API-011 正常 401/403/422 各变体的完整真实场景与回执。这些要求继续保留，不以现有能力或单元测试替代其端到端验收。

固定线的 `full_pack` 只覆盖当前最小 core-v1 八场景。MCP 三场景的 `selected_suites`、canary 的 `diagnostic_subset` 和固定八场景各自保留分母，不能合并为“全部 P0 通过”。S3/S4 产品化能力、真实宿主与其他部署档位的完成情况继续按上节未完成项记录。

最终整库 `make check`：**实际退出 0**，日志 `/tmp/flowtest-selftest-make-check-current.log`，留存副本为 `output/selftest-validation-20261023/checks/make-check-current.log`。后端格式、Ruff、mypy 452 文件通过，2196 passed / 14 skipped / 2 个已有 warning，覆盖率 91.29%；前端 format、ESLint、TypeScript、189 个文件 / 1450 项测试及生产 build 通过，statements 86.63%、branches 82.81%、functions 86.57%、lines 89.20%。完整检查前后 109 个改动代码/契约文件 SHA 一致，集合摘要为 `18eb2add564618f5548ab81d9f5250c867ba91705b565ce87760a4818a7df5e1`，详见留存的 `checked-source-snapshot.json`。这表示当前未提交工作区的完整本地检查通过，不是 Git HEAD 或远程 CI 状态。

安全验收制品已复制到工作区 `output/selftest-validation-20261023`（ignored），`artifact-index.json` 记录完整清单和每个文件的 SHA-256。内容包括构建绑定、manifest、采证、核验报告、双 JUnit、实际缺证据验收、对应源码快照和检查日志；不包含 `private.env` 或运行凭据。该本地留存保持 `local_untrusted`。四份严格 JSON Schema 的 Draft 2020-12 校验、六份仓库说明的本地链接与格式检查，以及 `git diff --check` 均通过。
