# 第三十四批：上下文检查器具名测试查询成本补修

基于 `9e7162d5e983ad55f022e4c6735bf537d19b348e`，在独立工作树 `task-plan-audit/FlowTest` 核查 M21 的两个临界测试。对应[冻结审计 M21](../../audits/2026-10-19/complete-audit.md#m21)与[实施方案 F-CTX-01](../../audits/2026-10-19/remediation-plan.md#f-ctx-01)；冻结文件未修改。本批仅调整[页面测试](../../../../../frontend/src/pages/ContextInspectorPage.test.tsx)的控件查询，不修改产品、接口、日志、诊断策略或 CI 配置，不增加审计完成计数。

## 证据与改动

正式 CI `39650707276` 中，`shows revision evidence, state knowledge and a proposal deep-link` 为 **53.324 秒**，`links a conflict to its exact frozen finding and reports filtered and total evidence counts without writes` 为 **56.856 秒**，均通过但接近既有 60 秒阈值。测试没有逐字输入，MSW 同步返回合成上下文，原有 `retry: false` 与 `motion: false` 保留。

在 Node `v22.22.0`、Vitest `4.1.10` 下，对两个具名测试分别执行修前、修后 CPU 采样，均使用 `CI=true` 与原有 pool、workers、timeout。角色查询的主要成本来自 `isInaccessible` 的 CSS 可见性链；修前该调用的包含耗时分别为 **5.942 秒**、**6.277 秒**。采样未出现 `getMissingError`、`prettyRoles` 或 `getRoles`，不能将静态发现的缺席角色诊断路径写成已证实原因。

最终只调整两个目标测试中的六处交互定位：

- 第一例的三个页签，先在已有公开标签“上下文详情”的 section 内按页签文字定位单个 `role="tab"` 控件。
- 第一例的查看证据按钮，以及第二例的定位冲突、查看证据按钮，使用同一详情区内已有公开 `aria-label` 精确定位。
- 每个替代查询都显式检查原角色、准确的可访问名称、可见性及没有 `aria-hidden="true"` 祖先，再继续真实 `userEvent.click`。保留原有 heading、证据内容、Provider、警告、知识关系、Proposal 链接、固定来源修订与文件路径、URL evidence/revision、筛选后与总计数，以及 `reads === 1`、`writes === 0` 的全部断言。

第二例仅替换首个页签查询的试验没有收益，已撤回；该例原有首个 `findByRole` 和后续证据详情、清除筛选、确定性、警告筛选的角色查询保持原样。未更改 timeout、workers、重试、覆盖率或视觉阈值，没有使用 `hidden: true`。

## 具名采样与验证

以下为各一次同命令具名采样，反映本机结果，不等同于远端重跑后的耗时保证。CPU 列为包含耗时，调用栈相互重叠，不能相加。

| 测试                          | 测试耗时：修前 → 修后 | 角色查询 CPU：修前 → 修后 | CSS CPU：修前 → 修后 |
| ----------------------------- | --------------------- | ------------------------- | -------------------- |
| Revision、知识与 Proposal     | 9.948 → 6.941 秒      | 6.063 → 0.040 秒          | 9.096 → 6.189 秒     |
| 冲突、固定 Finding 与只读筛选 | 10.528 → 7.658 秒     | 6.542 → 0.397 秒          | 9.645 → 6.807 秒     |

采样命令分别使用上述完整测试名作为 `-t`：`CI=true pnpm exec vitest run src/pages/ContextInspectorPage.test.tsx -t '<完整测试名>' --execArgv=--cpu-prof --execArgv=--cpu-prof-dir=<本工作树输出目录> --reporter=verbose --reporter=json --outputFile.json=<输出目录>/results.json`。目录与 JSON 均位于已忽略的 `output/validation/pr146-context-test/`；修前为 `before-revision/`、`before-conflict/`，最终修后为 `after-revision-buttons/`、`after-conflict-buttons/`，每个目录保留完整 `profile.log`、测试结果与原始 CPU profile，汇总为 `cpu-summary-final.json`。

最终实际执行并通过：

- `CI=true make test-frontend-targeted TARGETS='["src/pages/ContextInspectorPage.test.tsx","src/features/context-inspector/use-context-inspector.test.tsx","src/features/context-inspector/use-context-page.test.tsx"]'`：**3 文件、12 项通过**，15.72 秒；覆盖完整页面测试及上下文切换、固定修订、分页 hooks。
- 修改测试的 Prettier、ESLint（零警告）以及全前端 `pnpm exec tsc -b --pretty false` 通过。
- 本回执的格式、相对链接与 `git diff --check` 通过。

日志分别为 `targeted-final.log`、`format-test-final.log`、`eslint-final.log`、`typecheck-final.log` 与 `format-links-final.log`。全部诊断只使用既有合成测试数据，没有浏览器、共享 QA 或账号操作。

## 完成边界

本批完成以上测试查询补修与具名本地验证。未运行完整前端覆盖率、后端、Compose、Windows、发布验收或远端门禁，未推送、合并或部署。既有其他提交的全量结果不能替代整合后当前提交的正式 CI；PR 与发布状态由主代理另行核查。
