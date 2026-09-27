# 开发效率第三阶段：PR 验证路由与合并门禁

## 合并后状态与本次修正（2026-09-27）

三阶段代码已由 PR #112、#113、#114 顺序合并到 `main@0ad736efef03e46c2cfc7cb0e710a7dcd0dab319`。文档 PR #115 的最新 Head `abb9b4a8d1d53e6e08e5288aff396d7c56db995e` 通过自动 docs 路由，受信发布器给出正式 `Required Gate: success`；追加提交先使旧结果失效，无关标题编辑未覆盖有效结果。#115 已关闭，验证文件未合入。该证据仅覆盖文档路径与这些时序，不代表其他路径或全部并发交错已在线验收。

`main-required-gate` ruleset（id `21653796`）仍严格要求 GitHub Actions App（integration id `15368`）发布唯一 `Required Gate`，无 bypass、无 merge queue。合并后审计发现迁移/构建输入漏检、Compact 无生产者、治理 PR 重复全量执行、源码加测试回退全侧及事件并发风险。本修复分支保留现有架构，修改须经新的受控 Bootstrap 与最新 Head 远程检查后才算部署；下文原始性能/本地验证数字均是此前分支快照。

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

执行链使用只读 `pull_request` token。发布器只使用 `workflow_run` 的 requested/in_progress/completed 事件，只有读取元数据与写 Commit Status 的权限，不 checkout、不执行 PR 提供的脚本或产物，不恢复 PR 缓存。本修正将这些事件统一当作唤醒，按 Head 串行化并保留待处理事件，每次读取当前 run/attempt 的实际状态后发布 pending 或终态。正式 `Required Gate` 仍是 Commit Status，不能由同名 Check Run 替代。手动 `workflow_dispatch`、周期运行和影子结果都不发布该正式状态。

`workflow_run` 必须来自本仓库的 `PR Validation` 工作流和指定运行实例；发布器核对当前 PR 的 base/head、合并提交双亲、运行 ID/attempt、工作流 ID、Head、计划指纹和本轮 plan/shadow job 的实际成功结果。旧运行晚完成、标签切换或基线变化时，指纹或实例不匹配就不发布 success。所需 job 由影子汇总在同一 run 的 `needs` 中逐项判断；`skipped`、`cancelled`、`failure`、`missing` 不算通过。计划读取失败保持阻断。GitHub strict up-to-date 仍负责默认分支自行前进后的合并前更新要求。

治理保护包含 `.github/workflows/`、`.github/actions/`、AGENTS/CONTRIBUTING/Makefile/PR 模板、CI 说明、计划器、聚合器、发布器和定向测试包装脚本。改动这些文件时计划增加 `policy` 必需项，影子汇总及受信发布器均拒绝自行放行，必须走受控 Bootstrap。

本修正将决定镜像目标与缓存的 `backend/docker-bake.ci.hcl` 纳入同一治理清单。治理 PR 的普通链路只计算计划并明确报告 `bootstrap_only`，不再与专用 Bootstrap 链路同时运行两套完整作业；若同一 PR 还改动 Compact，仍执行独立的 Compact 兼容验收。专用链路按 PR 号取消旧 Head 的在途检查。正式状态仍只由默认分支发布器写入。

## 检查矩阵

| 最低档位 | 典型输入 | 本轮任务 |
| --- | --- | --- |
| docs | 独立 README 与 `docs/*.md` 说明，排除治理说明 | Quick CI 的 diff 检查；其他 job 标记 `not_applicable` |
| standard | 局部前后端或 Skill 包 | 相关侧格式、lint、类型与构建；命中的源码测试加直接消费者，未知映射回退该侧全部测试且不启用全局覆盖率；Skill 契约和已有 evaluation |
| integration | 共享前端、引擎/权限/模型、依赖、部署形态 | 相关侧完整覆盖率与集成；按领域增加 Compose、镜像审计、Windows、历史升级 |
| full | `ci:milestone`、未知根路径或完整回归 | 全量后端、前端、Compose、镜像扫描、Windows、升级与 Skill 检查 |

计划分开记录 `tier_floor`、最终 `tier`、领域、必需与不适用 job、理由、规则文件摘要以及 base/head/tested SHA。普通 Markdown 只有受限路径进入 docs；`docs/release/` 和 `docs/operations/` 中由测试读取或用于执行的文档进入后端检查，Skill 的 Markdown、fixture、生成输入和 CI 文档也按真实用途处理。新目录或未映射根路径升至 full。PR files API 使用每页 100 项，核对 `changed_files`，重命名同时读取新旧文件名，达到 3000 项上限或响应不完整即失败。文件名只作为 JSON 数据，不插入 shell 命令。

标准档后端定向入口禁用覆盖率，全侧回退也用 `--no-cov`；完整 Backend CI 的 90% 与 Frontend CI 的 80% 覆盖率阈值维持原样。依赖审计由 Security CI 执行，避免 Backend/Frontend full 作业重复执行同一审计。

本修正把 Alembic 实际配置的 `backend/migrations/` 与 `backend/alembic.ini` 纳入迁移/升级/Standalone 检查，并按实际 Dockerfile、补丁、dockerignore、Bake、nginx 和镜像清单选择构建、扫描及启动检查。Security 的 Bake 目标、镜像身份核对和漏洞扫描同时覆盖 Postgres WALG 镜像；新增扫描发现旧镜像存在可修复的高危项，因此固定 Postgres 17.11 基础镜像与 WAL-G v3.0.9 源码提交，用 Go 1.27.0 和已修补依赖重建。该镜像在本机使用与 CI 相同版本的 Grype 扫描为 High/Critical 0，正式结果仍以当前 PR 的远程检查为准。标准档的已知源码映射与 PR 明确改动的测试文件取并集；删除/重命名测试由 PR 文件元数据标记并回退完整侧测试，未知源码或共享 fixture 也保持回退。受信发布器不依赖自己 checkout 中的测试文件是否存在来重算计划。

`ci:light` 保留为兼容请求，不能降低代码变更的最低档位；`ci:milestone` 请求 full；双标签按较重请求执行并在原因中说明。相关标签增删与新 Head 使用同一 PR 活动并发组，较新运行替代旧运行；无关标签和普通标题/正文修改使用独立 ignored 组，不取消有效检查。目标分支编辑触发重新计划；默认分支自身前进由 strict up-to-date 阻止旧基线合并，不声称普通 `edited` 会覆盖它。

PR 验证运行将无关标签/元数据编辑标记为 `PR Validation ignored`，发布器只选 `PR Validation active` 运行。这样即使无关事件的全跳过 run 晚完成，也不会让有效运行失去最终汇总机会。

## 手动与周期入口

- 手动诊断：各 Backend/Frontend/Compose/Security/Windows/Upgrade 工作流保留 `workflow_dispatch`，被测提交以该运行的 `github.sha` 为准。它们不写 PR `Required Gate`。
- PR 完整验收：在开放 PR 上添加 `ci:milestone`，或在同一 PR 事件重跑本轮验证。移除标签重新回到路径风险最低档位；旧结果不能直接补绿。
- 周期回归：`Full Regression` 每周一 03:00 UTC 在受信默认分支运行一次，也允许手动启动。Compose 的 Compact/容量 RC 检查仍使用现有 `Compose Smoke Test` 的 `run_rc_gates` 手动开关；不把它伪装成普通 PR 的结果。
- `main` 上没有每次 push 无条件重复跑整套发布矩阵。周期结果不替代候选提交需要的当前验证，漏洞库扫描也不按源码 SHA 跳过。

`deploy/compact/` 的自动路由要求 `compact`。本修正为普通 Compact 变更新增当前 PR 内的六服务启动与业务流兼容 job，汇总器只接受该 job 的实际成功；普通 Compose smoke 不能替代它。原有备份/恢复、离线升级、容量与稳定性 RC 仍只在 P0/P1 复审清除后通过手动入口执行，自动兼容 job 不解除这项人工限制。

## 验证、性能与激活

以下为 PR #114 合并前的本地验证快照：计划/发布器单元测试覆盖 docs、局部前后端、引擎、权限、迁移、依赖、部署、Skill、治理路径、重命名与分页、标签最低档、聚合异常、旧 run、手动运行边界。后续远程运行记录见 PR #114；新审计修正须另看当前 PR 的检查。标准档未知源码仍回退完整侧测试，不能把并行 job 时间相加作为等待时间。

本地条件为 macOS、已有 uv 与 pnpm 依赖缓存，不代表 GitHub runner 的冷启动性能。集成期间一次完整后端 `pytest -q` 通过，墙钟 181.33 秒、覆盖率 90.67%（阈值 90%）；之后针对最终规则改动复跑 `pytest --no-cov tests/test_ci_plan.py tests/test_required_gate.py -q`，59 项通过。后端 `ruff format --check`、`ruff check`、`mypy app ../scripts/*.py`、`lint-imports` 通过。Skills 契约测试和 `build_skill_evaluation.py --check` 通过。前端 `pnpm format:check`、`pnpm lint`、`pnpm test:coverage`、`pnpm build` 通过；覆盖率测试为 88 个文件、425 项，Vitest 报告历时 172.65 秒，语句 85.71%、分支 80.72%。11 个工作流经 PyYAML 解析；本机无 actionlint，GitHub 平台语法及实际 job 命名尚未验证。Compose、Windows、历史升级及真实 PR E2E 未在本轮本地执行。

PR #114 的历史受控启用步骤及后续复测清单：

1. 先确认前两阶段依赖已经在受信基线，核对本分支相对最新 `main` 的差异及 Bootstrap 规则。
2. 维护者按现有 Bootstrap 治理流程审查并合入本阶段工作流、计划器与发布器。临时要求精确 Head 的 Bootstrap 子检查时，维持 GitHub Actions App 来源、strict 和无 bypass；普通合并后立即恢复唯一的 `Required Gate`，全程不关闭保护。
   `.github/workflows/ci-bootstrap-validation.yml` 对治理文件变更在 PR 事件中执行完整检查，供维护者核对精确 Head 后实施受控 Bootstrap；它不发布正式 `Required Gate`，普通功能 PR 不触发这套重复检查。
3. 在代表性文档、局部功能、关键修改 PR 上观察 `PR Validation` 与 `PR Validation Shadow` 的实际 job 名、运行 ID、被测 SHA、跳过状态及发布器 Commit Status；再做一次追加提交、标签变化、失败后重跑，并确认旧运行不能覆盖新结果。
4. 只有平台实测证明 `Required Gate` 的来源和状态被现有 ruleset 正确识别时才宣布激活。如工作流未触发或 publisher 无法可靠关联运行，保留保护并回滚到旧控制器/标签入口；不要以手动诊断成功补写 PR success。

PR #114 的 Bootstrap 合并与文档 PR #115 的正式门禁激活已完成。仍未完成：本次审计修复的远程 PR 验证、普通 Compact 兼容 job 的真实成功/失败样本、完整 Compact RC 的自动可信关联、更多功能路径与并发事件验收、基础镜像发布和跨工作流同产物复用。代码提交与本地通过不等于这些剩余项的发布验收。
