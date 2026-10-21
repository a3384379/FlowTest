# PR146 S22 浏览器验收同步回执

日期：2026-10-22。开发基线：`85da05813a63ddd892d348b1f4ad9b722d24ce25`。本次仅同步既有 S22 E2E 与 M26 已实现的平台对象选择、真实契约策略和深链接行为，不修改产品源码、后端或单元测试。

## 失败证据与原因

正式 run `39646234746` 的 `compose / smoke` 作业 `119383016263` 在第32步非 S29 浏览器验收失败，67项中66项通过。唯一失败为 `frontend/e2e/s22-capability-sdk.spec.ts` 原第26行：等待旧文案“固定 Schema 哈希”，首轮与既有自动重试均失败。完整原始作业日志保存在：

`/Users/sqz/.codex/worktrees/ui-v5-audit-followup/FlowTest/output/playwright/audit-20261019/remediation-pr146-85da058-compose-39646234746-full.log`

测试找到 HTTP 行后没有点击选择。M26 现在在无选择时展示空检查器，点击对象才读取精确版本详情，且策略展示改为实际 Manifest 字段，不再展示旧的通用 Secret 安全文案。选择后 URL 带 `id/version`，原刷新断言 `/platform$` 也需同步。这是验收路径漂移，日志和源代码未表明本次失败来自环境、网络超时或产品契约缺失。插件空态旧定位默认按子串匹配，本身并非另一项确定失败。

## 最小同步

- 保留可见菜单导航、分页寻找 HTTP 能力、安装按钮禁用、插件及 Runner 切换和池名称/网络区表头验证。
- 显式点击 HTTP 能力，捕获真实精确版本 GET 响应，核对能力标识、64位完整 Schema 哈希和检查器版本。没有创建模拟响应或硬编码示例数据。
- 打开“策略与来源”，验证服务端声明固定 Schema 哈希及加密凭据材料，并核对 UI 对应字段和“声明策略与实际请求级策略不同”的提示。未恢复旧的产品硬编码安全结论。
- 刷新时保留同一 `id/version` URL，验证同版本和完整哈希恢复；切到空插件目录及 Runner 后验证旧能力检查器清空。
- 未修改 Playwright 配置、超时、重试、视觉阈值、覆盖率门槛或 CI 治理。

## 验证与运行边界

修改文件的 Prettier、ESLint，以及包含 E2E 文件的专门 TypeScript 检查通过。`playwright test --config=playwright.config.ts --project=chromium --no-deps e2e/s22-capability-sdk.spec.ts --list` 识别1文件1测试；这仅为发现/加载检查，未启动浏览器。日志在本工作树 `output/validation/pr146-compose-s22/`。首次专门 TypeScript 命令因 TS6 要求显式 `--ignoreConfig` 被拒绝，已保存 `types.log`，修正命令后结果在 `types-final.log`，未放宽类型规则。

本地没有执行修改后的 S22 文件，没有运行全量、Compose 或浏览器，也未操作共享 QA、重置账号密码或导出会话。检查发现标准 `auth.setup.ts` 可能修改密码并保存认证状态，不能直接在共享 QA 上重复标准 setup。本次不创建临时配置或启动额外浏览器，由整合负责人通过已管理的隔离 bundled Chromium CLI 会话逐断言真实 GUI；该人工路径核验不能等同于实际执行本文件。正式新 head 的 Compose 独立测试数据库仍按既有 setup 与浏览器门禁实际验证本文件。

旧 head 的其他作业通过不能替代修复后新 head 的完整正式门禁。本地静态结果也不能证明此 S22 文件已通过真实浏览器验收。

## 整合后的GUI逐断言复核

整合负责人使用既有隔离 bundled Chromium CLI 会话逐断言复核，12项检查通过、实际业务写入0。真实目录分页后显式选择 `http.request@2.0.0`，精确GET返回完整Schema哈希 `783d919fe97bc9327de6b8d2f70479a10ba13114b081803339ed2b813ed33863`；URL固定ID和版本，刷新后恢复同一URL、身份和完整哈希。Manifest的Schema固定策略和加密凭据材料字段与检查器一致，页面保留声明策略与实际请求级策略的区别；安装继续禁用，插件和Runner类别切换后旧能力检查器清空。

日志位于主验收工作树 `output/playwright/audit-20261019/remediation-s22-gui-replay.log`，明确标记为GUI逐断言复核，**不是执行本S22 spec文件**。没有运行共享QA的标准setup或修改账号密码；本文件是否通过须以正式新HEAD Compose在独立测试数据库中实际执行的结果确认。精确 `9e7162d5e983ad55f022e4c6735bf537d19b348e` 的正式运行 [39650707276](https://github.com/a3384379/FlowTest/actions/runs/39650707276) 已结束。其Compose作业119398878639实际运行非S29浏览器集合67项，7.2分钟全部通过，包含本S22 spec；完整日志 `remediation-pr146-9e7162d-compose-full.log` 保留于主验收工作树。该次整体门禁因另一AI前端单测超时失败，不能用Compose成功记为完整门禁成功，也不能用本段实际spec结果改写上述GUI证据的性质。后续测试查询补修未改本S22文件，最新3fa完整正式运行39665397118另行独立确认，结果见下一段。

后续3fa运行39665397118的Compose作业119449068581也实际完成本S22 spec，S22未失败。其非S29集合总67项中66通过，另S19 Cron下拉视口检查首次失败后由既有重试通过，最终作业success；该次不是无重试67通过，完整日志 `remediation-pr146-3fa68ce-compose-full.log` 保留。独立零API诊断未复现S19持续裁切，未猜改产品，作为已有验收稳定性遗留单列，见[整合回执](batch-29-integration.md#s19-验收稳定性遗留)。随后整体正式前端182文件1353项及Required Gate均已success，完整分页审查通过，精确3fa68ce通过匹配HEAD命令合并PR146为main `e4bd5456c7a9f360643d1fad8f7eb37af959a4db`。合并后最终main回归另行执行，PR门禁不替代它。
