# PR146 组织审计测试查询补修回执

日期：2026-10-22。开发基线：`9e7162d5e983ad55f022e4c6735bf537d19b348e`。仅修改[组织治理测试](../../../../../frontend/src/pages/OrganizationGovernancePage.test.tsx)的两个既有审计用例和本回执；[M24 原回执](./batch-26-organization.md)的产品及权限边界保持。

## 诊断与对照

PR146 正式运行 `39650707276` 的完整前端日志中，这两例分别以55.364秒、54.570秒通过，接近既有60秒上限。该次完整前端另有 AI Viewer 超时，不能记为正式门禁成功。原始日志保留在主验收工作树 `output/playwright/audit-20261019/remediation-pr146-9e7162d-frontend-full.log`。

在 SIXTH 干净基线先逐例采样，再作补修。四次最终对照使用相同 Node v22.22.0、pnpm 11.25.0、`CI=true`、具名 `-t` 与 `--execArgv=--cpu-prof`；未传 pool、worker、timeout、retry 或 coverage 参数，沿用仓库配置。各智能体串行交接 CPU 窗口，采样期间没有并行测试、lint 或 types。

| 最终同条件对照         |           修改前 |           修改后 |
| ---------------------- | ---------------: | ---------------: |
| 第6页及筛选用例耗时    |         10.173秒 |          6.983秒 |
| 该例角色查询包含时间   | 6.063秒（49.9%） |  0.058秒（0.7%） |
| 该例可访问名称包含时间 |  0.206秒（1.7%） |  0.074秒（0.8%） |
| 该例样式计算包含时间   | 8.938秒（73.6%） | 6.061秒（68.8%） |
| 切组织及403用例耗时    |         10.185秒 |          7.207秒 |
| 该例角色查询包含时间   | 6.208秒（53.9%） |  0.061秒（0.7%） |
| 该例可访问名称包含时间 |  0.221秒（1.9%） |  0.097秒（1.1%） |
| 该例样式计算包含时间   | 9.174秒（79.6%） | 6.360秒（71.2%） |

百分比以完整 Node profile 区间为分母，含测试装载；两例修改前/后区间分别为12.149/8.806秒、11.518/8.935秒。调用链统计分别匹配 `queryAllByRole`、`computeAccessibleName` 和 `getComputedStyle`；包含时间相互重叠，不能相加，也不等于测试自身占比。本地采样没有完整覆盖率及正式 CI 的机器负载，不能由此保证远端耗时。

首轮只收窄卡片、行和 Dialog 查询、复用 userEvent 并粘贴完整筛选值，两例为10.119秒、10.384秒，没有明显收益。最终再将审计 Tab 和该记录已有标签的查看按钮定位到单节点，逐节点核对原 role、name、可见性及 `aria-hidden="true"` 祖先，取得表中结果。没有把104字符输入宣称为已证实的主要瓶颈，也没有把首轮结果冒充最终结果。

## 语义与范围复核

- Tab 通过现有公开文本定位实际 tab，保留原 `/审计与安全/` 可访问名称匹配；查看按钮限定第6页实际记录行并按已有标签定位，精确检查 button 角色和名称。两者显式检查可见性与自身/祖先没有 `aria-hidden="true"`，没有启用隐藏元素查询。
- Dialog、关闭、查询和治理组织 Select 继续使用默认可访问的角色查询。第6页资源先等真实行显示，再查看详情；原 Trace 和服务端允许详情断言保持。分页总数61、第6页请求及筛选后的第1页、page size、action、actor、resource type/id、起止时间全部 URL 断言保持。
- 四项筛选仍通过真实点击后粘贴完整值进入表单，两项日期保持原 change 事件；没有直接调用业务服务或改造请求响应。原 MSW GET 夹具及 `onUnhandledRequest: 'error'` 保持，没有添加宽泛写入成功响应。
- 切组织仍真实选择目录项、收到成员及审计403，并核对新组织请求从首页且不带旧 action。旧第6页资源和任意 Dialog 缺席继续查询全局 document，没有用旧卡片或已卸载节点替代全局负断言。
- 未改其他28项用例、共享 helper、产品、权限、采集策略、依赖、motion、CI、超时、worker、重试或覆盖率门槛。

## 实际验证与边界

`CI=true make test-frontend-targeted TARGETS='["src/pages/OrganizationGovernancePage.test.tsx","src/features/projects/DirectoryPicker.test.tsx","src/pages/organization-governance-rotation.test.tsx"]'`：3文件、34项全部通过，耗时42.89秒；本文件30项全部执行。修改文件 Prettier、ESLint、全前端 `tsc -b --pretty false`、文档格式/本地链接及 `git diff --check` 通过。

完整证据位于本工作树 `output/validation/pr146-organization-test/`：`before-filters/`、`before-scope/` 为原9e基线；`after-filters/`、`after-scope/` 保留首轮无收益结果；`after-semantic-filters/`、`after-semantic-scope/` 对应最终行为，后续仅有 Prettier 换行。各目录含原始 profile、JSON 测试结果和日志；`comparison-final.json`、`comparison-percentages.json` 及 `summarize_cpu.py` 可核对口径；`targeted-final.log` 为完整34项具名结果。按名称采样时其他29项未运行，最终文件级具名检查没有跳过本文件用例。

本次未启动浏览器、操作共享 QA，也未运行完整前端覆盖率、Compose、后端或构建。测试专属补修仍需整合后的最新 head 正式门禁；本回执不改变61项已完成加12项本地补修、58项已合并的既有状态，不宣称73项最终验收或已合并。
