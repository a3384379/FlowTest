# M11 测试工程整改记录

依据：[完整审计 M11](../../audits/2026-10-19/complete-audit.md#m11)、[修改方案 M11](../../audits/2026-10-19/remediation-plan.md#m11)。对应 `F-ENG-01/02/03`。

**三项已实现，具名专项、完整本地检查及真实浏览器验收通过，计入42项本地完成。** 当前42项本地完成、31项待完成、37项已合并，GitHub门禁和正式环境验收分别确认。

## 覆盖统计与审核任务

- 缺少coverage显示“未评估”，空列表显示“无可评估项”，均不渲染满进度圈。1/1为100%，0/1为0%；存在未评估行时列出缺失数量，摘要和表格使用同一完整设计分母。未修改覆盖引擎或历史设计内容。
- 主流程统一为来源与目标、测试目标及审核、场景审核、场景预期/直接覆盖/来源、完整来源与完整覆盖。S47、指纹、原始表达及JSON放入高级只读区。
- 选择场景联动其实际绑定的判断预期、直接覆盖路径和来源；检查场景不会修改冻结的生成选择。场景/资产列表每页10项，预期、覆盖及来源每页8项，长表局部横向滚动。
- 确定性、置信度、缺少唯一状态预期、冲突/不支持的Oracle以及必填路径省略均显式区分。仅设计场景不能勾选；已接受的仅设计Proposal仍禁止生成资产，并显示原因，不以人工接受覆盖可执行条件。
- 已知分类、覆盖维度及引擎要求显示中文；自定义来源要求与字段路径保留原文。认证要求区分必须/可选/无需认证，认证方式、位置及名称清楚展示，不更改契约值。

## 原始资产引用与刷新恢复

原Apply返回仅有数量，前端丢弃ID，历史用例草稿也会变化。本次在TestDesign添加有界原始引用：每个场景对应最初生成的Workflow和TestCase ID，和原有资产同事务写入。Proposal GET及Apply返回只读物化回执，按项目、TestDesign及source_change_set联合恢复；批量核对两类资产所属项目，外部引用不暴露。

- Apply成功保存回执、刷新相关工作流/用例目录缓存、将Proposal ID写入URL。刷新同一URL仍能找回每个资产，并跳到其准确工作流或用例草稿。
- 界面显示“已生成资产草稿”，发布/执行分别操作；不把原始引用冒充当前发布或执行状态。重复Apply沿用409和trace，失败保留原审核状态及错误，不显示虚假成功。
- 旧记录没有新引用时只恢复已保存且属于本项目的testcase://引用，明确标记历史不完整。不会从可变TestCase.draft_definition推断原工作流；聚合已丢失时明确无法恢复。
- 跳转来源或资产前检查未保存目标。取消保留输入；确认后打开准确路径。真实浏览器核对确认框只有一个可见标题且可按标题访问。

双向迁移：[0064](../../../../../backend/migrations/versions/20261021_0064_test_design_materialization.py)，升级添加非空JSON列、默认[]，回滚移除该列；原指纹和旧用例引用不变。回滚会丢弃新增的原始引用，旧记录兼容读取不猜工作流。

## 来源证据与请求边界

- 来源抽屉显示来源类型/语义、固定修订、字段路径、确定性及置信度。详细元数据按完整来源身份从原冻结contract及additional_evidence重建，放在DTO附加字段；不改domain EvidenceRef、设计序列化或fingerprint。
- 完整身份存在多组不一致元数据时不猜路径，显示未提供。引用缺少唯一来源时清除旧抽屉并说明；显式选择完整来源后清除旧警告。
- 只解析明确的api-definition://UUID/version/N、workflow://UUID和testcase://UUID。接口GET始终请求固定N；其他资产入口明确是当前目录。未知引用保留文本，不执行javascript:或猜外部链接。
- 来源读取失败保留身份、路径和trace，重试同一版本。没有自动Review/Apply/Publish/Execute，也未扩大日志、真实响应采集或脱敏政策。
- 写入需要权限成功读取且具备edit。异步操作以项目/Proposal/工作区生命周期校验响应归属，切项目、切Proposal或离开页面后的迟到成功/失败不能污染当前上下文。

## 本地检查与审计补修

1. 重构前基线：后端29项，前端2文件5项；提取UI组件后同2文件5项通过，重构独立提交fa2aed8。
2. 后端最终具名4文件34项通过：`test_design_asset_migration.py`、`test_test_engineering_assets.py`、`test_flow_spec.py`、`test_test_engineering.py`。覆盖多资产恢复、编辑可变用例后仍保留原工作流、冻结设计/指纹不变、重复Apply、跨项目/Viewer、被篡改外部引用以及SQLite双向迁移。
3. 前端4文件25项通过；浏览器发现业务标签残留后补中文展示及自定义要求保留测试，4文件26项通过，最后认证标签补修页面9项通过。具名测试涵盖0/1/空覆盖、仅设计禁写、精确来源v1失败重试、未知来源不导航、缓存回执、跨项目/Proposal迟到成功及失败、刷新、未保存跳转保护。
4. 额外审计发现离开工作区后的异步回执仍可落入缓存：新增卸载复现，修复前1失败/7通过；生命周期清理后8项通过，完整受影响集25项通过。日志 `remediation-engineering-unmount-before.log`、`remediation-engineering-frontend-targeted-r12.log`。
5. 后端精确树 `24f0584db804775d4b88af8853cbab0af63dff46` 完整检查通过：Ruff格式/检查、mypy442文件；1882项通过、14跳过、2项既有警告，覆盖率91.07%。日志 `remediation-engineering-backend-full.log`。
6. 标签补修前a0439bd前端完整检查：164文件1090项通过，无未处理异常，覆盖率85.93/81.96/85.55/88.41%，格式/lint/类型/构建通过。其后源码 `84af5eaa401d3930b98fe7e06cf91d00e06e60b9` 前端树 `5b03dad3b9971cbbd40a838d580bb6da7660d420` 独立完成最后完整复验：164文件1091项通过，无未处理异常，覆盖率85.94/81.95/85.55/88.41%，格式/lint/类型/构建通过，日志 `remediation-engineering-84af5ea-frontend-full.log`。两次完整检查期间应用与测试源码冻结，后续整合仅文档变动。

检查中的自有问题均保留失败日志：整页getByRole在JSDOM中递归计算CSS导致停滞，CPU采样确认后改为准确控件与局部查询，未增加超时/跳过或削弱断言；后续测试作用域、Element类型和微任务时机错误已修正。浏览器首次关闭按钮误用英文Close，实际中文为“关闭”；负向来源第一次只拦首个503被既有自动重试恢复，调整为持续503直至手动重试，保留真实失败可见及同版本读取断言。

## PostgreSQL与真实浏览器

独立Compose `flowtest-product-completion`，13078端口、隔离Chromium；专用项目 `39cdfda0-3a69-4269-a91d-109d92507a22`，唯一标记 `隔离合成审计M11-1792555951200`。没有修改用户3000端口或其他项目。

- 首次空表0063→0064→0063→0064通过后，又在专用项目插入1条明确的旧格式合成设计记录，停backend/worker再复验升级/回滚/再升级。前后旧记录数1，指纹和case refs聚合哈希始终21ff270c4e28488c52e28a5c2882caae，新列在升级后[]、回滚后不存在。最后重启服务，readiness200。该往返在新物化资产生成前完成，未删除新回执。
- 真实OpenAPI导入产生9场景，选择正常请求和超过最大值两项。按页面显式创建、接受、生成草稿，恰好3次命令；生成2个工作流及2个用例，刷新恢复原ID，来源固定1.0.0及body.quantity可检查，页面异常0。
- 原Proposal `9693712b-c80e-4b25-960f-76a9edb86e57`。未保存输入的取消/确认导航到准确Workflow，用例入口到准确case draft；检查阶段写命令0。
- 手机首次切视口即采样为437px；DOM诊断确认响应式布局稳定后document/body均390px，根内容宽366px，未发现持续溢出。补验等待实际布局稳定，来源抽屉x0/宽390/高844，截图实际进入视口后再采集；不是用裁切隐藏错误。桌面document1440px。
- 旧版无响应契约读取实际v1。持续503显示trace后手动重试，2次自动尝试失败+1次手动成功，均固定v1。仅设计Proposal `2e002f3e-5fc8-4e56-a224-11ae0f17e0b4` 可以接受，但资产生成按钮禁用并说明缺少唯一状态预期；仅创建/审核2次命令，Apply0次，页面异常0。

日志保存在忽略的 `output/playwright/audit-20261019/`：`remediation-engineering-postgres-legacy-migration.log`、`remediation-engineering-positive-browser-resume.log`、`remediation-engineering-navigation-mobile.log`、`remediation-engineering-mobile-stable.log`、`remediation-engineering-design-only-browser-r2.log`；另保留早先失败及诊断记录。截图 `remediation-engineering-assets-desktop.png`、`remediation-engineering-assets-mobile.png`、`remediation-engineering-source-mobile.png`、`remediation-engineering-design-only-desktop.png`。

## 改动与待确认

- 后端：[物化与只读恢复](../../../../../backend/app/services/test_engineering_proposals.py)、[证据元数据](../../../../../backend/app/services/test_engineering.py)、[DTO](../../../../../backend/app/schemas/test_engineering.py)、[模型](../../../../../backend/app/models/test_design.py)、[资产回归](../../../../../backend/tests/test_test_engineering_assets.py)。
- 前端：[测试工程](../../../../../frontend/src/pages/TestEngineeringPage.tsx)、[状态与回执](../../../../../frontend/src/features/test-engineering/use-test-engineering.ts)、[证据工作区](../../../../../frontend/src/features/test-engineering/DesignEvidenceWorkspace.tsx)、[资产清单](../../../../../frontend/src/features/test-engineering/MaterializedDesignAssets.tsx)、[覆盖摘要](../../../../../frontend/src/features/test-engineering/DesignCoverageSummary.tsx)。
- 最后标签版本只读复验确认正常请求/超过最大值等业务标签，原资产引用仍可恢复；1440/390px、写命令0及页面异常0，日志 `remediation-engineering-final-readonly.log`，最终桌面及手机资产/覆盖截图已目视复查。本批最新HEAD正式Required Gate、审查、合并及合并后回归仍需独立完成。尚未做正式部署、真实Windows实体终端与全站设计签收。原冻结73项审计及方案保持不变。

## 契约中心标签补修后的整合复验

整合M10的正式门禁补修194e376后，源码 `4dcfc223e1aa963ebf0facd0a93d75f3588a8d41` 的前端树 `1e918ff43a52ff76338fd8b35c7da53edebdad66` 已重新完成7文件48项受影响专项及完整前端检查：164文件1092项通过，无未处理异常，覆盖率85.97/81.95/85.61/88.45%，格式、lint/类型与构建通过。日志 `remediation-engineering-contract-label-integrated-targeted.log`、`remediation-engineering-contract-label-frontend-full.log`。后台树仍为24f0584db804775d4b88af8853cbab0af63dff46，与1882项/91.07%完整通过一致。

同步只在进度/验证文档保留测试工程42项/31项待完成的最新状态，并补入M10失败及补修回执，没有改写冻结审计或物化快照。当前42项本地完成、37项已合并，任务执行2项仍在验收，未计入完成。M10的最新194e376正式门禁39546205418仍在运行；本批GitHub PR与正式验收另行确认。
