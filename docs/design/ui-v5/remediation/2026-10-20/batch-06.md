# 用例目录任务筛选整改

对应 `F-CASE-04`。依据：[完整审计](../../audits/2026-10-19/complete-audit.md#f-case-04)、[详细方案](../../audits/2026-10-19/remediation-plan.md#f-case-04)。本批解决用例和用例集目录的查询范围、最近运行证据及选择一致性。

## 查询与交互合同

- 发布状态区分“已有发布版本”和“仅草稿（从未发布）”，不将已有版本但仍在编辑的资产误称为未发布，也不推断草稿是否改变。
- 最近结果在全部版本的真实历史中选择最近一次运行，再按状态和环境筛选。较旧失败或旧环境不能替代最新通过；数据集子执行不重复成为最近根执行。
- 区分未运行、排队、运行、通过、失败、取消及隔离。尚无根执行的计划条目保留排队/隔离等真实状态；不会提供虚构的报告 ID。
- 环境指最近运行实际使用的环境；用例集匹配该次运行任一成员的环境。表格原环境列标为“草稿绑定环境”，以区分用途。没有运行记录的资产不匹配具体历史环境。
- 环境选项来自本项目实际历史，包含归档环境，支持服务端搜索、分页及选中 ID 回显。不会截取当前环境目录前 100 项；不按名称推断环境映射。
- 排序支持最近修改、名称升/降序、最近运行，均含稳定 ID 次序。列表、total、目录及未分类计数采用同一筛选合同，数量由服务端计算。
- URL 保存搜索、标签、发布状态、最近结果、环境、排序及两类资产的页码。筛选变化回到第一页；保留目录、详情对象及固定版本。非法 URL 显示错误并停止目录查询，重置后恢复。
- 批量选择只作用于当前页。切筛选、目录、类型或页码会清理选择；刷新后已离开结果集的对象不会继续参与移动、计划、导出或删除。
- 最近用例结果直接返回该次执行的固定用例版本和来源：版本链接进入不可变版本，报告链接进入实际执行；未生成执行的计划条目进入对应计划。不会使用当前草稿补造历史版本。
- 可见活动运行会刷新目录；最后一个活动结果完成后再刷新目录计数。直接运行或计划入队也会使相关资产、目录和历史环境缓存失效。手动刷新入口保留。

## 并发读取补修

用例的筛选记录、最近运行元数据和总数原先分次读取，在读取间新增运行时，可复现返回一条记录但 total 为 0。独立测试对用例集和报告也复现了相同问题。

三类列表现通过一次 SQL 取得排名页、总数及对应行；空页也返回完整范围 total。共享的只读分页实现见 [catalog_paging.py](../../../../../backend/app/repositories/catalog_paging.py)。测试使用两个独立会话，在第一次读取结果后精确暂停并提交新的状态，再检查同一个 HTTP 响应，没有通过重复请求掩盖竞态。

这保证一个列表响应内部的一致性；目录计数与列表是独立 HTTP 请求，并不声称它们在并发写入时属于同一个数据库事务。筛选合同一致，运行完成和用户刷新会同步更新展示。

## 改动入口

- 领域合同：[asset_catalog.py](../../../../../backend/app/domain/asset_catalog.py)。
- 最新历史与目录查询：[asset_catalog.py](../../../../../backend/app/repositories/asset_catalog.py)、[test_assets.py](../../../../../backend/app/repositories/test_assets.py)。
- 服务和 API：[test_assets.py](../../../../../backend/app/services/test_assets.py)、[test_assets.py](../../../../../backend/app/api/v1/endpoints/test_assets.py)。
- 范围与筛选：[asset-catalog-scope.ts](../../../../../frontend/src/features/test-assets/asset-catalog-scope.ts)、[AssetCatalogFilters.tsx](../../../../../frontend/src/features/test-assets/AssetCatalogFilters.tsx)。
- 运行证据及页面：[CaseCatalogResult.tsx](../../../../../frontend/src/features/test-assets/CaseCatalogResult.tsx)、[TestAssetsPage.tsx](../../../../../frontend/src/pages/TestAssetsPage.tsx)。
- 后端回归：[test_asset_catalog_api.py](../../../../../backend/tests/test_asset_catalog_api.py)，含 121 条跨页、105 个历史环境、最新结果优先、计划等待、归档环境、非法输入、外项目隔离、空页和三类并发响应。
- 前端回归：[asset-catalog-scope.test.tsx](../../../../../frontend/src/features/test-assets/asset-catalog-scope.test.tsx)、[AssetCatalogFilters.test.tsx](../../../../../frontend/src/features/test-assets/AssetCatalogFilters.test.tsx)、[CaseCatalogResult.test.tsx](../../../../../frontend/src/features/test-assets/CaseCatalogResult.test.tsx)、[TestAssetsWorkspace.test.tsx](../../../../../frontend/src/pages/TestAssetsWorkspace.test.tsx)、[use-test-assets.test.tsx](../../../../../frontend/src/features/test-assets/use-test-assets.test.tsx)。

没有数据库结构变更，无需迁移；不修改历史快照、发布/执行权限、日志或诊断捕获策略。旧列表参数继续兼容，新最近运行字段为附加响应字段。

## 验证记录

专项后端 70 项通过，前端 7 文件 50 项通过；历史环境选择器 1 项、空页 total 3 项另行通过。格式、Ruff、mypy 430 文件、前端 lint 和生产构建通过。三类并发测试先复现失败，再全部通过；日志保留在 `output/playwright/audit-20261019/`。

完整 `make check`、浏览器专项及 GitHub 交付的最终结果将在验证结束后补齐；本条记录不代表完整门禁已经通过。
