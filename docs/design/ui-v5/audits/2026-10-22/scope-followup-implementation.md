# FlowTest 组织切换边界整改实现记录

日期：2026-10-22。基于[修复前审计](scope-followup-audit.md)和[详细修复方案](scope-followup-plan.md)。基线：`104e09f276699a0ae89e74cc23b786d6ed7e1481`，分支：`codex/scope-reconciliation-20261022`。

## 1. 实现范围

| 问题                    | 实现及实际消费者                                                                                                                                                                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| C-M06-01 项目成员与权限 | 命令捕获原项目/团队/目录；边界错误先取消准确原查询，再失效且不跨组织重读。常驻 ProjectProvider 进入项目时恢复显式失效目录，显式失效/错误的角色不可信，保留原列表优先级。共享精确 QueryCache invalidation 订阅覆盖权限、工作流、用例、项目治理与通知写入口；普通自然 stale 与后台读取不因此降权。 |
| C-M15-01 报告通知       | 创建与启停在身份边界异常中先取消原通知目录查询，再失效。Secret 和提示继续受原命令身份守卫约束，返回后读取真实目录，不自动重发写入。                                                                                                                                                              |
| C-M19-01 发布判断       | 取消原判断分页及最新判断查询，再按原项目失效。证据、输入和搜索/分页 pending 锁定及正常刷新等待保持。                                                                                                                                                                                             |
| C-GLOBAL-01 接口与标签  | 取消原对象各版本详情及定义恢复读取；记录原 epoch/user/organization 的专用恢复标记。真实标签消费者只在原身份恢复后读定义，成功后清标记。标记专用前缀保留到权威读/正常成功/会话清空，避免五分钟 GC 丢失恢复入口；当前选择、固定版本和草稿保持。                                                    |

本轮没有修改后端业务、响应身份拦截器、数据库、依赖、测试超时/重试/覆盖率或 CI 治理。共享 `projects` 目录因成员变更而取消/标记失效，但不清空已有数据；其他项目的独立权限、成员和详情缓存保持。查询取消阻止旧回执写回，不宣称一定中止未消费 AbortSignal 的 HTTP 传输。

## 2. 独立 max 复审追加问题与验证状态

独立复审没有仅复用作者绿灯，另外确认并修复六类同范围 P2：权限晚到旧 GET、通知晚到旧 GET、发布判断晚到旧 GET、接口恢复标记 GC、常驻项目上下文恢复、显式失效后权限 GET pending 期间仍使用旧权限。每类均保留原始红例；正式测试补齐后，独立原字节反例重新验证。

- 通知/发布独立旧读取探针：3/3 转绿，`review-reports-release-late-reads-green.log`，源码运行前后一致。
- 权限晚读和常驻上下文独立探针：2/2 转绿，`review-access-provider-green.log`。
- 最终权限 pending 与通知/发布独立探针：4/4 转绿，8.78 秒，`review-shared-guard-final-green.log`，12 个产品与 4 个测试文件的 before/after SHA 一致。
- API 独立正式回归：6/6 转绿，`review-api-final.log`，包括离开六分钟后真实非活跃标签恢复。

以上组别有重叠，不能相加作唯一场景总数。最终独立报告为本地 `output/scope-remediation-20261022/review-scope-max.md`；独立终审在最终源码上确认没有剩余可操作 P1/P2。兼容检查发现，显式失效收紧权限时原成员输入表单会消失；现改为保留禁用表单，并将同项目全局命令 pending 纳入重开面板的锁定条件。既有三项慢刷新回归与独立七项检查已通过。扩大回归为 32/33 通过，唯一新增重开用例触及 60 秒上限；阶段诊断确认耗时集中于两次 RTL 可访问角色查找，放行写响应后 97 毫秒内正常收敛。仅改用页面既有标签/文本精确定位后，该例 1/1 通过、其余 9 项按名称过滤，28.72 秒，保留整个真实项目页、全部禁用/刷新/一次写断言及原测试时限。组合证据不能写为一次 33 项全绿；最终完整检查另行覆盖。普通自然 stale 的对照保持可编辑；没有把每次后台读取都解释为权限失效，也没有用响应到达时间重新定义角色权威优先级。

## 3. 具名验证

- 报告/发布：新增正式 `ReportsReleaseSessionBoundary.test.tsx` 19 项，加既有 `ReportsNotificationsIsolation.test.tsx` 与 `ReleaseGatePage.test.tsx`，45/45 通过，29.38 秒；包括真实 SDK transport 晚到后不可覆盖新数据。日志 `reports-release-targeted-final.log`；随后共享权限守卫的最终消费者由权限正式测试及最终完整检查继续覆盖。
- API：新增正式 `ApiRenameSessionBoundary.test.tsx` 6 项，加既有 ApiConsolePage、WorkspaceObjectTabs 和 API Hook 回归，42/42 通过，83.94 秒。日志 `api-targeted-final.log`。
- 权限：正式 `ProjectAccessSessionBoundary.test.tsx`、`ProjectProvider.test.tsx`、`ProjectsPage.test.tsx` 和 `use-test-assets.test.tsx` 的扩大组 32/33 通过（`access-final-regression-green.log`）；唯一超时例仅调整定位查询后具名单跑通过（`access-reopened-pending-green.log`），其余产品源码不变。独立兼容复跑 7/7 通过（`review-pending-compatibility-final-green.log`），包括旧三项慢刷新契约。
- 精确改动文件格式和 ESLint 按最终文件重新验证；统一 `pnpm build` 已通过最终产品源码的 TypeScript 与生产构建（`frontend-build-final.log`）；最终完整检查将再验证提交中的全部测试和构建。开发中发现的新测试 ByRoleOptions 类型参数及 ProjectsPage 复杂度 11 均已修正，没有改规则或阈值。

原始日志和逐文件 SHA 位于本地 ignored 目录 `output/scope-remediation-20261022/`。审计临时探针运行后移出前端默认发现路径；正式新增回归位于 `frontend/src/`，未修改测试发现配置。

## 4. 实页与交付证据边界

使用独立 SQLite Standalone 临时服务与测试数据、Playwright bundled Chromium/Chrome for Testing、独立 profile，桌面视口 1440×900。真实接口 PATCH 已执行后，通过浏览器后退进入组织并切换治理组织，再放行原响应，浏览器前进返回项目：非活跃 B 标签恢复真实新名称，当前 A 和请求路径保持，PATCH 仅一次，无错误组织下原项目读取。截图和脚本位于 `output/playwright/scope-remediation-20261022/`。通知创建、启停也分别完成同样的真实服务写入后组织往返验证，每次仅一次写入、错误组织下原项目读取为零，返回后目录/开关恢复且无旧 Secret 对话框。该检查不等同于 Compose 部署形态验收。

前两次实页脚本试图在重命名 pending 时关闭对话框，没有完成目标路由条件，且一次清理路由时出现“Route is already handled”。其原始日志保留，不作产品失败或通过证据；最终有效路径采用真实浏览器历史后退/前进，不绕过应用缓存或修改内部状态。

本记录随实现候选提交。候选提交的完整本地 `CI=true make check`、最新 Head 远程 Required Gate、合并状态及后续实页结果另以实际 PR 和最终本地交付清单为准；在这些结果产生前，不把局部绿灯称为完整门禁或发布验收。旧 PR #148 的成功状态不计入本轮整改。当前路径投影要求 quick、frontend-full 与 compose；最终仍以远程可信计划和实际结果为准。

## 5. 未覆盖的发布验收

本轮前端行为与缓存协调不改变 API 合同或迁移。生产部署、实体旧安装、真实外部 LLM/MCP/Runner/KMS、容量 RC 未执行；其他部署形态只在实际运行适用验收后记录。不能由本地 SQLite、MSW、源码复审或旧 PR 的 Compose/Windows 绿灯推导这些验收已通过。
