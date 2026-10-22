# FlowTest 整改修改正确性复审

日期：2026-10-22。审计对象：[PR #148](https://github.com/a3384379/FlowTest/pull/148)。本文件保存修复前审计快照；正文中的“本轮”指修改正确性复审阶段。后续修复状态另见[整改实现记录](scope-followup-implementation.md)，不使用后来的绿灯覆盖原反例。

## 1. 结论

本轮确认 **4 个 P2 残余问题**，没有确认新的 P0、P1 问题。先前“全部闭环”的结论偏乐观：正常响应路径已修复，但项目成员、报告通知、发布判断、接口重命名遗漏了组织身份变化后的缓存协调。

四项共用的触发条件是：写请求已经发送，用户离开页面并进入组织治理，响应返回时组织身份已改变。真实 API 客户端会把旧身份响应转为 `SessionBoundaryError`，相关 mutation 的 `onSuccess` 因此不会执行。服务端可能已经成功写入，但原项目缓存没有更新，也没有标为失效。

最终归档的反例使用真实页面组件或 Hook、真实 SDK、Axios 身份拦截器和 MSW 合成 HTTP 服务。8 个场景中，4 个普通卸载对照通过，4 个组织切换场景发生业务断言失败；没有超时。另行重跑已有 AI 组织边界回归，4 项全部通过。

这些反例证明前端缓存协调存在遗漏，不代表已在真实后端或浏览器中完成这四条路径的端到端复现。成员权限问题是旧权限缓存与控件状态风险，未证明可以绕过后端授权。

## 2. 审计范围与源码绑定

| 项目                   | 本轮核对结果                                                                         |
| ---------------------- | ------------------------------------------------------------------------------------ |
| 修改前基线             | `1038e08ffe078719b7d0fe357d7bc7d0d4a1029a`                                           |
| 被审计分支 Head        | `755aab7f5a32d852ee85c4746e2933e51bef372f`                                           |
| GitHub 合并提交        | `104e09f276699a0ae89e74cc23b786d6ed7e1481`                                           |
| Head 与合并提交的 Tree | 均为 `c07cad925f5d7ae4a1eba4e4c78ac16a5b814efd`                                      |
| 变更范围               | 51 个文件，包含 29 个产品文件、19 个测试文件、3 份文档                               |
| 本轮文件校验           | 48 个代码与测试文件的 SHA-256 与最终完整检查绑定记录全部一致                         |
| 工作区                 | `/Users/sqz/.codex/worktrees/protocol-audit-ci-followup/FlowTest`                    |
| 工作区保护             | 原项目目录已有的 AGENTS.md、README.md、.playwright/ 修改保持原样；未切换或重置原目录 |

本轮围绕上一轮 11 项整改及其跨模块消费者核对差异，重点检查权限、身份边界、缓存、异步提交和响应取消。没有重新对原方案全部 26 个模块做一次视觉验收，不能由本报告推导“全部设计能力已经实现”。

参考材料为已提交的[原审计报告](complete-review.md)、[原修改方案](remediation-plan.md)、[实现记录](implementation-report.md)，以及本地 v5 交接包中的流程编排交互与状态契约。流程统一 Environment、节点 Service/Endpoint Variant、草稿与发布版本、历史执行只读等既有合同保持作为核对基准。

## 3. 已确认问题

### C-M06-01：成员变更的组织边界响应未失效原权限缓存（P2）

位置：[AccessManagementPanel.tsx](https://github.com/a3384379/FlowTest/blob/104e09f276699a0ae89e74cc23b786d6ed7e1481/frontend/src/features/projects/AccessManagementPanel.tsx)，第 100–122 行，尤其第 120–122 行的 `onError`。

对应原整改：R-M06-01。

复现条件：当前用户为普通用户，具有直接 Owner 成员身份；项目另外还有一名 Owner，且当前用户具有 Viewer 团队授权。这样移除自己的直接成员身份是合法场景，移除后仍可只读访问项目。反例实际点击成员表的移除按钮与确认按钮，发送 DELETE，然后卸载页面并调用真实组织切换入口，最后放行合成服务的 204 响应。

预期：原项目权限缓存被重新读取或标为失效。返回原项目时不能继续把旧 Owner 当作当前有效权限。

实际：普通卸载对照更新为 Viewer；组织切换场景确认写入已执行、客户端确实抛出 `SessionBoundaryError`，但原 `['project-permissions', projectId]` 仍为 Owner，且 `isInvalidated === false`。不是“移除最后一名 Owner”被后端拒绝的场景。

原因：成员、团队、权限和项目摘要的协调全部放在 `onSuccess`；`onError` 只控制错误提示，未协调原项目缓存。生产默认查询新鲜期为 15 秒，快速返回时可能复用旧权限；具体控件显示还取决于消费者和返回时机。

建议：在 mutation 发起时捕获原项目及操作涉及的团队身份；遇到类型明确的身份边界错误，按实际缓存前缀仅将原范围权限、成员和摘要标为失效，不携带当前组织头主动重读原范围。保留现有正常成功路径的所有权限重读汇聚和失败收敛。

证据：最终统一反例日志（`output/postmerge-correctness-20261022/scope-receipts-canonical.log`），`access command` 的普通对照通过、组织切换断言失败。原始反例第 145–182 行。

### C-M15-01：报告通知创建后的组织边界响应未失效原通知目录（P2）

位置：[use-reports.ts](https://github.com/a3384379/FlowTest/blob/104e09f276699a0ae89e74cc23b786d6ed7e1481/frontend/src/features/reports/use-reports.ts)，第 80–92 行，尤其第 83–85 行。

对应原整改：R-M15-01。

复现条件：报告页发起通知渠道创建，POST 进入合成服务后卸载页面并切换组织，随后返回 201。

预期：即使旧页面不能消费响应中的一次性 Secret，原项目通知渠道目录也应失效，返回后从服务端重读。

实际：合成写入已执行且仅发出一次；真实 API 拦截器抛出身份边界错误后，原 `['notification-webhooks', projectId]` 仍保留空数组且未失效。普通卸载对照会正确失效。

原因：创建与启停渠道都只在 `onSuccess` 中失效目录，没有身份边界错误分支。创建已通过反例确认；启停采用同样处理方式，属于源码确认的同类遗漏，本轮未额外运行启停专用反例。

建议：为创建与启停 mutation 增加按输入中原 projectId 失效的边界错误分支，使用 `refetchType: 'none'`；继续由现有命令身份守卫控制弹窗、提示和一次性 Secret。不得为补缓存而把旧 Secret 展示到新页面，也不得自动重发创建。

证据：最终统一反例日志（`output/postmerge-correctness-20261022/scope-receipts-canonical.log`），`webhook command`；原始反例第 62–87 行。

### C-M19-01：发布判断的组织边界响应未失效原判断目录（P2）

位置：[use-release-gate.ts](https://github.com/a3384379/FlowTest/blob/104e09f276699a0ae89e74cc23b786d6ed7e1481/frontend/src/features/release-gate/use-release-gate.ts)，第 139–148 行，尤其第 142–147 行。

对应原整改：R-M19-01。

复现条件：发起发布判断后离开页面并切换组织，在新组织身份下收到原请求的 201 响应。

预期：原项目判断目录与最新判断缓存失效，返回时能重新读取已创建结果。

实际：合成服务确认创建已执行；客户端抛出真实身份边界错误，原 `release-decisions` 目录仍未失效。普通卸载对照通过。`release-latest-decision` 与目录处于同一个仅成功回调中，源码显示也会跳过失效；本轮动态断言覆盖目录。

影响：快速返回可能暂时看不到刚创建的判断。用户据此再次提交可能产生重复操作，但本轮没有验证真实服务的重复创建结果，不能宣称已复现重复数据。

建议：捕获原 projectId 的类型化错误分支同时失效目录与最新判断，暂不重读；保留现有输入、搜索、分页锁定和同步防重，不把身份边界异常当作已确认未写入，也不自动重试写请求。

证据：最终统一反例日志（`output/postmerge-correctness-20261022/scope-receipts-canonical.log`），`release command`；原始反例第 89–114 行。

### C-GLOBAL-01：接口重命名的组织边界响应留下旧定义与标签名称（P2）

位置：[use-api-console.ts](https://github.com/a3384379/FlowTest/blob/104e09f276699a0ae89e74cc23b786d6ed7e1481/frontend/src/features/api-console/use-api-console.ts)，第 203–227 行，尤其第 227 行。

对应原整改：R-GLOBAL-01。

复现条件：对接口发起重命名 PATCH，响应前卸载工作区并切换组织，随后收到成功响应。

预期：原接口的定义、详情及目录得到可靠协调；返回原身份时通过真实读取确认最终名称，不能长期优先使用旧稳定定义。

实际：普通卸载对照将 PATCH 返回定义写入稳定键；组织切换场景确认合成更新已执行和真实边界异常，但 `apiDefinitionKey(projectId, apiId)` 仍为旧名称且未失效，详情、列表的成功失效回调也被跳过。

真实消费者：[WorkspaceObjectTabs.tsx](https://github.com/a3384379/FlowTest/blob/104e09f276699a0ae89e74cc23b786d6ed7e1481/frontend/src/features/navigation/WorkspaceObjectTabs.tsx) 第 256–266 行优先从稳定定义缓存取名称。因此此遗漏会使标签继续采用旧名称，直到其他正常读取覆盖该缓存。这里的稳定键由 `setQueryData` 写入，单纯标为失效不会自动产生读取，修复时还须验证实际标签消费者。

建议：类型化边界分支取消原接口可能迟到的详情读取，并将原目录、各版本详情和稳定定义的状态协调到可重新确认状态。恢复原身份后，通过有效的定义读取或既有详情读取补全稳定定义；保留当前接口选择、固定版本及本地草稿。继续保留取消后 `signal.throwIfAborted()` 的写入防线，不能在错误分支直接把输入名称当作已确认的服务端结果。

证据：最终统一反例日志（`output/postmerge-correctness-20261022/scope-receipts-canonical.log`），`API rename`；原始反例第 116–143 行。标签影响依据实际消费者源码，未另行进行浏览器截图验收。

## 4. 共同原因与已有正确实现

真实响应拦截器位于 [api.ts](https://github.com/a3384379/FlowTest/blob/104e09f276699a0ae89e74cc23b786d6ed7e1481/frontend/src/lib/api.ts) 第 30–34 行；身份比较包括 epoch、userId 和 organizationId，第 157–174 行。`setOrganizationId` 只改组织身份。组织治理页面第 136–139 行会在进入、切换与离开时更新该值，因此触发条件有真实产品入口。

[main.tsx](https://github.com/a3384379/FlowTest/blob/104e09f276699a0ae89e74cc23b786d6ed7e1481/frontend/src/main.tsx) 第 16–29 行配置 15 秒查询新鲜期，且仅在 epoch 改变时清空 QueryClient。单独切换组织不会自动清空这些项目缓存，不能假设旧回调被丢弃后自然得到正确状态。

AI 审核与组织服务账号已经采用类型明确的边界错误协调。AI 普通建议与变更集的 workflow/test_case 四个正式回归本轮重新运行全部通过，见 AI 正向回归日志（`output/postmerge-correctness-20261022/ai-boundary-positive.log`）。这些路径可作为实现参考，但不应无条件将所有错误、所有组织或全部缓存一并清空。

## 5. 按整改项复核结果

“未发现新增可确认问题”仅表示本轮源码与证据核对未确认新的缺陷，不代表穷尽全部行为，也不把此前测试算作本轮重跑。

| 原整改项                         | 本轮结论             | 核对内容与证据边界                                                                                        |
| -------------------------------- | -------------------- | --------------------------------------------------------------------------------------------------------- |
| R-M11-01 Standalone 设计资产兼容 | 未发现新增可确认问题 | 补已有 0064 的列、默认值、重复启动及原值保持；源码和已有测试核对，本轮未重跑旧包升级                      |
| R-M20-01 AI 结果消费             | 未发现新增可确认问题 | 原项目、结果类型、成功失效与边界错误协调；正式 AI 边界回归本轮四项通过，包含与 M22 的组合                 |
| R-M15-01 报告通知                | 有残余问题           | 正常项目切换守卫、Secret 隔离与输入锁定保留；C-M15-01 组织边界目录失效遗漏                                |
| R-M06-01 成员权限                | 有残余问题           | 正常成功路径的所有刷新等待、错误时不信任旧 Owner、消费者显式能力判断正确；C-M06-01 边界异常未协调原权限   |
| R-GLOBAL-01 接口名称同步         | 有残余问题           | 正常成功取消各版本旧请求、消费 AbortSignal 和稳定键写入有效；C-GLOBAL-01 边界异常留下旧定义               |
| R-M01-01 Dashboard 关闭能力      | 未发现新增可确认问题 | 当前 flags 成功且完成读取才消费能力，关闭或失败时不把暖缓存详情计入指标；本轮源码核对                     |
| R-M01-02 Dashboard 团队项目      | 未发现新增可确认问题 | 复用既有受权项目集合，保持组织约束、去重及直接角色优先级；本轮源码与已有授权测试核对                      |
| R-M19-01 发布判断提交            | 有残余问题           | 正常 pending 期间表单、证据选择、搜索和分页锁定及同步防重保持；C-M19-01 边界异常失效遗漏                  |
| R-M22-01 AI 变更集审核           | 未发现新增可确认问题 | 原 scope 捕获、输入锁定、等待失效与类型化边界协调；正式 AI 边界回归本轮四项通过，包含与 M20 的组合        |
| R-M24-01 组织账号表单            | 未发现新增可确认问题 | 稳定表单、按身份重建、成功才清空、一次性 token 与边界错误回退；本轮源码核对，未重新执行整个组织测试文件   |
| R-M25-01 Runner 事件下钻         | 未发现新增可确认问题 | 受权只读投影、原 task/lease/details 保持、可空字段与旧服务兼容；本轮源码及已有测试核对，未连接真实 Runner |

计数为上一轮 **11 项整改中 4 项存在残余，7 项未发现新增可确认问题**。这不是整个产品完成度百分比，也不是把 4 个缓存问题解释成 4 个模块完全不可用。

## 6. 本轮实际验证与历史门禁

### 6.1 本轮新执行

| 检查                                  | 实际结果                                            | 证据                                                                             |
| ------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------- |
| 最终统一反例，8 项                    | 4 对照通过、4 边界业务失败，退出码 1，21.61 秒      | 完整日志（`output/postmerge-correctness-20261022/scope-receipts-canonical.log`） |
| 正式 AIReviewSessionBoundary.test.tsx | 4 项通过，退出码 0，9.37 秒                         | 完整日志（`output/postmerge-correctness-20261022/ai-boundary-positive.log`）     |
| 48 个代码与测试文件 SHA-256           | 全部匹配最终 Head，Head 与合并 Tree 相同            | 机器可读摘要（`output/postmerge-correctness-20261022/validation-summary.json`）  |
| 生产源码与 Git 状态                   | 没有产品修改或新提交；被审计工作区 tracked 状态干净 | 机器可读摘要（`output/postmerge-correctness-20261022/validation-summary.json`）  |

反例在前端目录临时执行，随后按原字节归档到仓库根 ignored 输出目录，避免污染日后 Vitest 默认发现范围。未修改测试排除配置、覆盖率、重试、超时或 worker 设置。归档哈希与路径见 probe-manifest.json（`output/postmerge-correctness-20261022/probe-manifest.json`），原始源码见 scope-receipts.test.tsx（`output/postmerge-correctness-20261022/probes/scope-receipts.test.tsx`）。

准备阶段日志也保留：`access-boundary.log` 为按钮语言定位准备失败；`access-boundary-final.log` 为未补足另一名 Owner 条件的早期 fixture；`access-boundary-legal.log` 为合法权限条件的独立验证。前两者不作为产品结论。`scope-receipts-first.log` 是前三项的初步有效反例。最终结论和唯一 8 项计数统一使用最终归档源码对应的 canonical 日志，避免重复计数与版本混用。

### 6.2 核对过的历史检查，不是本轮重新执行

最终 Head 的此前 `CI=true make check` 退出码为 0，开始于北京时间 11:39:28，结束于 12:12:24，源码运行前后一致；后端 1955 passed、14 skipped，覆盖率 91.22%；前端 185 文件、1403 项通过，Statements 86.56%，完整格式、静态检查和构建通过。记录见 最终完整检查摘要（`output/full-remediation-20261022/local-final/make-check-result.json`）及源码绑定（`output/full-remediation-20261022/local-final/head-binding.json`）。

该 Head 的 [远程运行 39717995253](https://github.com/a3384379/FlowTest/actions/runs/39717995253)通过适用 integration 作业及正式 Required Gate，PR #148 已合并。具体绑定见 远程门禁证据（`output/full-remediation-20261022/remote-gate-final.json`）和交付记录（`output/full-remediation-20261022/github-delivery-final.json`）。既有测试未覆盖本次四条边界，门禁通过与存在这四条残余问题可以同时成立。

没有独立的合并后 main 流水线；上述 PR 门禁不能称为合并后另一次 CI。此前 Compose 浏览器及 Windows、历史升级门禁属于该 Head 的历史验收，本轮没有重新执行；容量步骤被跳过，实体旧安装、真实外部 LLM/MCP/Runner/KMS、容量 RC、生产部署仍不能由这些绿灯推导。

## 7. 后续处理边界

按成员权限、通知渠道、发布判断、接口名称的顺序补齐边界协调，详细落地步骤、测试矩阵和交付标准见[对应修复方案](scope-followup-plan.md)。审计当时四项仍未修复，本快照不将当时建议视为已实现；后续状态见整改实现记录。

本轮没有重新运行完整 make check、后端测试、Compose 浏览器、Windows 打包、历史升级、容量或生产部署。原目录的个人修改没有纳入 PR #148 审计，也没有被改动。原始审计日志保存在本地输出目录，不随仓库交付；本文件作为修复前快照保存。可复核的正式测试、命令及后续状态在整改实现记录和对应 PR 中列明。
