# 服务目录与精确上下文整改

日期：2026-10-21。对应 `F-SVC-01`、`F-SVC-02`、`F-SVC-03`，依据[完整审计](../../audits/2026-10-19/complete-audit.md#m03)与[详细方案](../../audits/2026-10-19/remediation-plan.md#m03)。本批已完成本地完整验证；远端门禁和合并单独记录。

## 服务目录及详情

目录采用服务端搜索、分页和稳定排序，搜索名称、服务标识及描述，`total` 来自完整匹配范围；不再用前 100 条的浏览器过滤代替完整搜索。分页行与总数在同一条 SQL 中读取，空页保留完整 total。搜索变化重置页码，选中 ID 独立于搜索和页码，URL 保存目录条件。详情按 ID 单独受权读取，页外对象可以打开；不存在、外项目或无权限对象不会退回当前页其他服务。

桌面为服务列表与就地详情。详情呈现目录服务 ID、标识、描述、契约类型、依赖角色、更新时间、已知契约版本及真实入口。新建仍为独立弹窗。手机选中对象后展示详情页，返回恢复目录；详情状态隐藏项目统计卡片以留出首屏阅读空间，长名称和 ID 可换行。

目录服务是契约目录身份，请求目标 Service 使用独立身份。本批没有通过相似名称或同名对象创建两者之间的映射。项目统计和既有依赖图继续读取项目级真实汇总；目录表格使用自己的完整匹配 total。

## 固定契约版本目录

新增按选中服务读取的只读版本目录，支持服务端分页、全范围 total 和空页，读取失败提供重试，切服务重新从第一页读取。

- OpenAPI 记录来自 `provider_service_id` 的正式绑定，显示导入时记录的提供方版本、来源名称、导入状态和时间。
- Pact 记录来自消费者/提供方正式引用，显示消费者版本，并明确本服务在该记录中是消费方、提供方或两者。
- 缺失版本号明确标为未记录，导入失败保留失败标签。展开行可以查看/复制实际记录 ID 和登记时间；不会把导入记录当成部署安全结论。
- 列表来自不可变导入记录的元数据，不使用当前 API 草稿补造历史版本。接口不返回契约内容、Credential 或 Secret。

## 契约和影响上下文

跨模块使用明确的 `contractServiceId`。兼容旧的 `focus=contract_service:<id>`；旧 `service_id` 只在影响页面兼容，不作为任意页面的请求目标 Service 定位。非法显式 ID 不回退到另一个旧参数或其他服务。

契约页面按指定 ID 补取页外服务并选择对应提供方，刷新和历史返回保留定位。没有 Pact 时保留该服务的准确空状态。项目契约目录的范围在页面说明中单独标明，避免将其他项目记录当成所选服务的矩阵证据。

影响列表与详情按冻结变更中保存的目录服务标识精确关联，并验证目录服务属于当前项目。列表分页和 total 使用相同条件；显式打开其他服务的记录返回 404。没有关联时显示服务范围空态，可以主动回到项目全部范围。未记录服务标识的旧分析不猜测、不回填，保留在项目范围中。

新的影响分析由人工选择的输入决定。如新记录不属于当前服务，页面在显示新记录时转到项目范围；若请求完成前用户已经切换页面范围，则保持用户后来的选择。回归通过精确暂停创建响应复现原错误 URL，并验证修复后的最终范围。

## 权限与状态补修

服务登记使用项目能力接口，不再从当前目录缓存的角色字符串推断写权限。权限未就绪或读取失败时禁止登记。已打开表单在权限撤销后转为只读，保留输入并停止提交；跨项目切换使用独立工作区，旧请求完成不关闭新项目的登记状态或显示迟到通知。

功能关闭仍保留稳定路由和明确说明，不请求可选业务资产；详情不会永久显示加载状态。精确对象读取失败不展示其他对象或把失败伪装成空结果。既有发布、执行、出站策略、日志及诊断捕获边界未扩展。没有数据库结构变更，无需迁移，也没有自动审核、发布或执行新增草案。

## 实现与测试入口

- 服务查询及授权：[contract_hub.py](../../../../../backend/app/services/contract_hub.py)、[contract_hub.py](../../../../../backend/app/repositories/contract_hub.py)。
- 固定版本合同：[service_catalog.py](../../../../../backend/app/domain/service_catalog.py)、[contract_hub.py](../../../../../backend/app/schemas/contract_hub.py)。
- 影响范围：[impact.py](../../../../../backend/app/services/impact.py)、[impact.py](../../../../../backend/app/repositories/impact.py)。
- 目录工作区：[ServiceCatalogPage.tsx](../../../../../frontend/src/pages/ServiceCatalogPage.tsx)、[use-service-catalog.ts](../../../../../frontend/src/features/services/use-service-catalog.ts)。
- 精确定位与上下文：[contract-service-location.ts](../../../../../frontend/src/features/services/contract-service-location.ts)、[use-contract-service-context.ts](../../../../../frontend/src/features/services/use-contract-service-context.ts)、[ContractServiceContextNotice.tsx](../../../../../frontend/src/features/services/ContractServiceContextNotice.tsx)。
- 版本阅读：[ServiceContractVersions.tsx](../../../../../frontend/src/features/services/ServiceContractVersions.tsx)。
- 后端回归：[test_contract_hub.py](../../../../../backend/tests/test_contract_hub.py)、[test_impact_engine.py](../../../../../backend/tests/test_impact_engine.py)。
- 前端回归：[ServiceCatalogPage.test.tsx](../../../../../frontend/src/pages/ServiceCatalogPage.test.tsx)、[ContractHubPage.test.tsx](../../../../../frontend/src/pages/ContractHubPage.test.tsx)、[ImpactAnalysisPage.test.tsx](../../../../../frontend/src/pages/ImpactAnalysisPage.test.tsx)、[ServiceContractVersions.test.tsx](../../../../../frontend/src/features/services/ServiceContractVersions.test.tsx)。

## 验证记录与交付边界

专项后端 13 项、前端 36 项通过；覆盖 105 条服务搜索和跨页、106 条版本记录、精确角色与缺失版本、外项目/未知 ID、空页、读取失败与重试、权限撤销、页外对象、旧链接及迟到创建响应。Ruff、mypy 431 文件、前端 lint/类型及生产构建通过。

真实 Compose PostgreSQL 验证创建两组明确标识的合成服务及其 OpenAPI 版本和影响分析；A/B 各自的服务范围均返回唯一所属记录，跨服务详情返回 404。仅在专用审计栈启用 Contract Hub、契约测试和影响分析开关，产品默认开关未修改。导入生成的候选保持未审核状态，没有执行 Review/Apply/Publish/Execute。原项目草稿未修改。

完整 `make check` 已通过：后端1777项、13跳过、2项既有警告，覆盖率90.83%；前端145文件、942项，无未处理异常，语句/分支/函数/行覆盖率85.65% / 81.74% / 85.04% / 88.12%。完整格式、Ruff、mypy、lint、类型与构建通过。源码提交 `8fb8e50c042532caaf97b96a6061d702ccb6eb94`，后端树 `cb50407fd505ba51d4cb7aae3e568a7a61a383b2`，前端树 `e0285e659a4001423ba66120d9999b01ebbced6c`，完整日志 `remediation-service-catalog-make-check-r2.log`。

真实 PostgreSQL 另验证同一个 Pact 在A/B两个服务中分别显示提供方/消费方，均保留同一消费者版本，版本总数各3。浏览器验证服务A到契约页仍选择A、影响页仅显示A的分析、固定版本目录和返回路径。手机390px时文档宽381px，没有横向溢出，选中服务后仅显示详情，返回恢复目录；详情首屏隐藏项目统计。桌面及手机版本阅读截图已逐张检查，保留于 `output/playwright/audit-20261019/`。

第一次完整检查在前端 lint 阶段发现详情组件复杂度超标，已经拆分职责后重新专项通过，并启动完整检查；未放宽复杂度、覆盖率、超时或跳过条件。既有项目图接口未进行容量验收，本批不宣称大规模图读取性能已经验证。
