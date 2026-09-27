# 开发效率第三阶段：PR 验证路由与合并门禁

## 交付状态（2026-09-27）

本分支提供确定性计划器、自动 PR 验证链、影子汇总与受信状态发布器代码。本轮尚未把它们部署到默认分支，也没有真实 PR 运行证据。`main` 的有效 ruleset `main-required-gate`（id `21653796`）要求严格更新，并要求 GitHub Actions App（integration id `15368`）发布名为 `Required Gate` 的结果；没有 merge queue。当前默认分支仍运行旧的加标签控制器。治理文件变更受现有 Bootstrap 规则限制，本分支不能通过修改自身的门禁来给自己放行。

本分支以 `codex/dev-efficiency-phase2` 的 `31a11e4` 为起点；第一阶段定向测试入口和第二阶段 Bake/缓存代码在此 checkout 中可用，但尚未进入当时的 `origin/main`。因此第三阶段的线上启用依赖前两阶段的受控交付和本阶段的 Bootstrap 审核。

## 架构与可信边界

```text
PR opened / synchronize / reopened / ready / 相关标签 / base 编辑
  → PR Validation 的 plan job：PR API 完整分页、确定性计划
  → 按计划运行 quick、标准检查或现有 workflow_call 全量检查
  → PR Validation Shadow：原生 needs，失败/跳过/缺失即失败
  → Required Gate Publisher：受信默认分支重新读取 PR 与计划，
     核对本轮 workflow run、被测合并提交、计划指纹和影子结果，
     发布唯一 Required Gate Commit Status
```

执行链使用只读 `pull_request` token。发布器只使用 `workflow_run` 的 requested/in_progress/completed 事件，只有读取元数据与写 Commit Status 的权限，不 checkout、不执行 PR 提供的脚本或产物，不恢复 PR 缓存。pending 绑定当前运行；延迟到达的 requested/in_progress 事件若发现运行已完成，就不再覆盖终态。正式 `Required Gate` 仍是 Commit Status，不能由同名 Check Run 替代。手动 `workflow_dispatch`、周期运行和影子结果都不发布该正式状态。

`workflow_run` 必须来自本仓库的 `PR Validation` 工作流和指定运行实例；发布器核对当前 PR 的 base/head、合并提交双亲、运行 ID/attempt、工作流 ID、Head、计划指纹和本轮 plan/shadow job 的实际成功结果。旧运行晚完成、标签切换或基线变化时，指纹或实例不匹配就不发布 success。所需 job 由影子汇总在同一 run 的 `needs` 中逐项判断；`skipped`、`cancelled`、`failure`、`missing` 不算通过。计划读取失败保持阻断。GitHub strict up-to-date 仍负责默认分支自行前进后的合并前更新要求。

治理保护包含 `.github/workflows/`、`.github/actions/`、AGENTS/CONTRIBUTING/Makefile/PR 模板、CI 说明、计划器、聚合器、发布器和定向测试包装脚本。改动这些文件时计划增加 `policy` 必需项，影子汇总及受信发布器均拒绝自行放行，必须走受控 Bootstrap。

## 检查矩阵

| 最低档位 | 典型输入 | 本轮任务 |
| --- | --- | --- |
| docs | 独立 README 与 `docs/*.md` 说明，排除治理说明 | Quick CI 的 diff 检查；其他 job 标记 `not_applicable` |
| standard | 局部前后端或 Skill 包 | 相关侧格式、lint、类型与构建；命中的源码测试加直接消费者，未知映射回退该侧全部测试且不启用全局覆盖率；Skill 契约和已有 evaluation |
| integration | 共享前端、引擎/权限/模型、依赖、部署形态 | 相关侧完整覆盖率与集成；按领域增加 Compose、镜像审计、Windows、历史升级 |
| full | `ci:milestone`、未知根路径或完整回归 | 全量后端、前端、Compose、镜像扫描、Windows、升级与 Skill 检查 |

计划分开记录 `tier_floor`、最终 `tier`、领域、必需与不适用 job、理由、规则文件摘要以及 base/head/tested SHA。普通 Markdown 只有受限路径进入 docs；`docs/release/` 和 `docs/operations/` 中由测试读取或用于执行的文档进入后端检查，Skill 的 Markdown、fixture、生成输入和 CI 文档也按真实用途处理。新目录或未映射根路径升至 full。PR files API 使用每页 100 项，核对 `changed_files`，重命名同时读取新旧文件名，达到 3000 项上限或响应不完整即失败。文件名只作为 JSON 数据，不插入 shell 命令。

标准档后端定向入口禁用覆盖率，全侧回退也用 `--no-cov`；完整 Backend CI 的 90% 与 Frontend CI 的 80% 覆盖率阈值维持原样。依赖审计由 Security CI 执行，避免 Backend/Frontend full 作业重复执行同一审计。

`ci:light` 保留为兼容请求，不能降低代码变更的最低档位；`ci:milestone` 请求 full；双标签按较重请求执行并在原因中说明。相关标签增删会重新验证。无关标签和普通标题/正文修改不会执行 plan 或取消在途检查。目标分支编辑触发重新计划；默认分支自身前进由 strict up-to-date 阻止旧基线合并，不声称普通 `edited` 会覆盖它。

PR 验证运行将无关标签/元数据编辑标记为 `PR Validation ignored`，发布器只选 `PR Validation active` 运行。这样即使无关事件的全跳过 run 晚完成，也不会让有效运行失去最终汇总机会。

## 手动与周期入口

- 手动诊断：各 Backend/Frontend/Compose/Security/Windows/Upgrade 工作流保留 `workflow_dispatch`，被测提交以该运行的 `github.sha` 为准。它们不写 PR `Required Gate`。
- PR 完整验收：在开放 PR 上添加 `ci:milestone`，或在同一 PR 事件重跑本轮验证。移除标签重新回到路径风险最低档位；旧结果不能直接补绿。
- 周期回归：`Full Regression` 每周一 03:00 UTC 在受信默认分支运行一次，也允许手动启动。Compose 的 Compact/容量 RC 检查仍使用现有 `Compose Smoke Test` 的 `run_rc_gates` 手动开关；不把它伪装成普通 PR 的结果。
- `main` 上没有每次 push 无条件重复跑整套发布矩阵。周期结果不替代候选提交需要的当前验证，漏洞库扫描也不按源码 SHA 跳过。

`deploy/compact/` 的自动路由明确加入 `compact` 必需项。现有 Compact RC 作业写明须在 P0/P1 复审清除后才手动执行；本阶段没有获得解除该限制的证据，因此自动链路不把普通 Compose smoke 冒充 Compact 通过，`compact` 当前保持缺失并阻断此类 PR。维护者完成复审并设计可关联当前 PR 的受信 RC 入口前，该路径不能由新门禁放行。

## 验证、性能与激活

本地已核对规则集和原有工作流，计划/发布器单元测试覆盖 docs、局部前后端、引擎、权限、迁移、依赖、部署、Skill、治理路径、重命名与分页、标签最低档、聚合异常、旧 run、手动运行边界。实际命令与结果以交付记录为准；尚无新工作流在 GitHub 上的运行、消耗分钟数或缓存命中数据，不宣称固定提速。预期省去的工作是文档 PR 的应用构建、局部前端 PR 的无关后端升级与 Windows 打包，以及旧控制器最长 90 分钟的轮询 runner 占用；标准档回退完整侧测试时仍需执行该侧测试。不能把并行 job 时间相加作为等待时间。

本地条件为 macOS、已有 uv 与 pnpm 依赖缓存，不代表 GitHub runner 的冷启动性能。集成期间一次完整后端 `pytest -q` 通过，墙钟 181.33 秒、覆盖率 90.67%（阈值 90%）；之后针对最终规则改动复跑 `pytest --no-cov tests/test_ci_plan.py tests/test_required_gate.py -q`，59 项通过。后端 `ruff format --check`、`ruff check`、`mypy app ../scripts/*.py`、`lint-imports` 通过。Skills 契约测试和 `build_skill_evaluation.py --check` 通过。前端 `pnpm format:check`、`pnpm lint`、`pnpm test:coverage`、`pnpm build` 通过；覆盖率测试为 88 个文件、425 项，Vitest 报告历时 172.65 秒，语句 85.71%、分支 80.72%。11 个工作流经 PyYAML 解析；本机无 actionlint，GitHub 平台语法及实际 job 命名尚未验证。Compose、Windows、历史升级及真实 PR E2E 未在本轮本地执行。

受控启用步骤：

1. 先确认前两阶段依赖已经在受信基线，核对本分支相对最新 `main` 的差异及 Bootstrap 规则。
2. 维护者按现有 Bootstrap 治理流程审查并合入本阶段工作流、计划器与发布器。临时要求精确 Head 的 Bootstrap 子检查时，维持 GitHub Actions App 来源、strict 和无 bypass；普通合并后立即恢复唯一的 `Required Gate`，全程不关闭保护。
   `.github/workflows/ci-bootstrap-validation.yml` 对治理文件变更在 PR 事件中执行完整检查，供维护者核对精确 Head 后实施受控 Bootstrap；它不发布正式 `Required Gate`，普通功能 PR 不触发这套重复检查。
3. 在代表性文档、局部功能、关键修改 PR 上观察 `PR Validation` 与 `PR Validation Shadow` 的实际 job 名、运行 ID、被测 SHA、跳过状态及发布器 Commit Status；再做一次追加提交、标签变化、失败后重跑，并确认旧运行不能覆盖新结果。
4. 只有平台实测证明 `Required Gate` 的来源和状态被现有 ruleset 正确识别时才宣布激活。如工作流未触发或 publisher 无法可靠关联运行，保留保护并回滚到旧控制器/标签入口；不要以手动诊断成功补写 PR success。

当前未完成：Bootstrap 合并、上述真实 PR 事件验证、正式门禁显示与约束验证、Compact RC 的自动可信关联、跨平台/Compose 全量执行、实测耗时比较。代码提交与本地通过不等于门禁激活或发布验收完成。
