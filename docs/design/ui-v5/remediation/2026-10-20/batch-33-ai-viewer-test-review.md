# PR146 AI Viewer 测试查询补修回执

日期：2026-10-22。开发基线：`9e7162d5e983ad55f022e4c6735bf537d19b348e`。仅修改 `frontend/src/pages/AIAssistantPage.test.tsx` 的三个既有用例和本回执，不修改产品源码、MSW 响应、权限、执行或诊断策略。

## 正式失败与诊断

PR146 正式运行 `39650707276` 在上述 head 的前端完整检查中，182文件共1352项通过、1项失败。唯一失败是 Viewer 待审建议可读及禁写用例超过原60秒上限，实际64.941秒；整个文件117.916秒，完整前端3696.77秒。该次其他选中作业（包括 Compose 67项、S22、后端1948项）通过，不能据此把 Required Gate 记为成功。完整原始失败日志保留在主验收工作树：

`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/remediation-pr146-9e7162d-frontend-full.log`

Viewer 本身没有 JSON 或备注逐字输入；夹具为已完成任务，MSW 立即返回且既有 QueryClient 禁止重试。使用相同 `CI=true`、测试名和 Node CPU 采样参数在 FIFTH 对照，确认主要成本来自角色查询、可访问名称和 JSDOM 样式计算，未发现长请求等待或新的产品缺陷。

| 相同具名采样            |   修改前 |  修改后 |
| ----------------------- | -------: | ------: |
| Viewer 用例耗时         | 12.850秒 | 7.474秒 |
| Viewer 角色查询调用链   |  9.812秒 | 4.547秒 |
| Viewer 可访问名称调用链 |  5.170秒 | 0.102秒 |
| Viewer 样式计算调用链   | 12.087秒 | 6.780秒 |
| Owner 接受用例耗时      |  3.349秒 | 3.162秒 |
| 拒绝及非法接受用例耗时  |  5.536秒 | 5.398秒 |

调用链为包含时间，彼此重叠，不能相加；本地采样不等同于正式 CI 的机器负载及覆盖率成本。两个 Owner 用例仅小幅改善，不作显著提速结论。曾试验用公开标题定位 Modal 再显式核对 role/name/visible，Viewer 为7.912秒，没有额外收益，已撤回，最终没有增加该抽象。

## 最小改动与断言保留

- Viewer 从已显示的建议标题定位真实表格行，在该行查询接受、拒绝和查看按钮；新建按钮限定当前页面标题区。两处样本开关按已有标签定位，并显式核对 switch 角色、可见性、准确可访问名称及自身/祖先没有 `aria-hidden="true"`，保留原角色查询的公开可达语义。
- 禁用按钮仍执行真实 `userEvent` 点击，之前和之后的零写入计数、全局无 Dialog、实际只读 Dialog 可见、备注 readonly、确认接受按钮缺席均保留。全局 Dialog 空断言继续查询整个 document，未改成会漏掉 Ant Design portal 的局部查询。
- Owner 接受动作限定实际建议行，编辑控件和确认按钮限定实际审核 Dialog，备注改为真实点击后一次粘贴；编辑后的完整请求体和人工确认备注断言保持。
- 拒绝后等待刚关闭的已审核 Dialog 真正卸载，然后仍核对全局没有任何 Dialog；拒绝请求体、第二行接受、非法 JSON 错误及零接受请求保持。
- 其他四个短用例保持不变。没有使用 `hidden: true`、模拟样式或产品测试特判，也未改超时、worker、重试、覆盖率门槛、依赖及 CI 配置。

## 验证与边界

`CI=true make test-frontend-targeted TARGETS='["src/pages/AIAssistantPage.test.tsx", "src/pages/AIAssistantRemediation.test.tsx", "src/features/ai/ai-service.test.ts", "src/features/ai/use-ai-review.test.tsx"]'`：4文件、30项通过，包含本文件全部7个用例。修改文件格式、ESLint、TypeScript 和 `git diff --check` 通过。

完整诊断和具名日志保存在本工作树 `output/validation/pr146-viewer-test/`：`before/`、`after-visible/` 为 Viewer 最终同条件采样，`before-owner/`、`after-owner-final/` 为两个 Owner 用例最终同条件采样。`after/`、`after-owner/` 保留初次收窄结果，随后独立复核要求给标签定位补显式可见性/名称断言，最终已重新采样和验证；`after-final/` 保留已撤回 Modal 试验的记录。`viewer-comparison-final.json`、`owner-comparison-final.json`、`summarize_cpu.py` 可核对计算口径，`targeted-visible-final.log` 为最终4文件结果。按测试名筛选时其他用例未执行，最终具名检查未跳过这7个用例。

本次没有启动浏览器、操作共享 QA、密码或会话，也未运行完整前端覆盖率、Compose、后端或构建。测试专属改动的最新正式门禁仍需在整合源码冻结后执行；本地通过不能替代新 head 的 Required Gate、审查、合并及合并后回归。此前85本地完整前端和9e正式其他作业成功仍分别绑定其原始源码，不改写失败历史。

## 整合后的独立复核补充

精确整合 `60f931d` 的再次只读复核发现，上述开关最初的 role/name/visible 断言遗漏了祖先 `aria-hidden`：`toBeVisible` 检查 CSS 和 HTML hidden，但不能排除只在祖先设置 `aria-hidden="true"` 的元素。原角色查询默认会排除这种元素。两处均补充 `closest('[aria-hidden="true"]')` 为空，覆盖元素自身及全部元素祖先；其他角色查询、全局缺席断言及业务行为未改。

补充后同一4文件30项再次通过，耗时32.81秒，完整日志为主验收工作树 `output/playwright/audit-20261019/remediation-ai-aria-final-targeted.log`。上表 CPU 采样属于追加这两条断言前的测试源码，不冒充追加后的重新采样。整合负责人停止旧树完整前端 r5（退出130）并请求取消旧60f门禁39664876063；两者均不计为完整通过，最终整合源码另行运行完整前端和正式门禁。
