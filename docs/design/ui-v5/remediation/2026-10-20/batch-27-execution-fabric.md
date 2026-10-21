# M25 分布式执行面整改回执

对应冻结审计：F-FAB-01、F-FAB-02。开发基线：`edb06bbc5259f0390b85bb45f731e72fd2fc8242`。

## 实现

- 队列按类型数字由服务端 SQL 对当前组织及共享项目或全部组织进行全量聚合，返回统计范围和生成时间。排队、租用是当前任务状态，失败是保留历史累计；分页任务目录不再充当统计分母。
- Pool、任务、Lease、事件使用真实总数及有界分页。新增管理员 Pool、Runner、任务精确读取；任务 Lease、事件按任务筛选。共享 Pool 的任务事件同时应用项目组织边界。
- 可见页每 15 秒刷新，后台暂停，提供手动刷新和最近成功读取时间。读取失败保留缓存并明确过期；任务或 Lease 刷新失败期间有效性显示待核对。
- 任务 ID 打开只读证据，展示执行、Runner、Lease、Fence、重试、错误和时间；支持页外 URL 定位及工作流执行、报告来源入口。Lease 区分当前 Fence、过期记录和历史状态。
- 保留原注册令牌、Drain/Resume 行为、权限、功能关闭边界、调度和 Lease/Fence 状态机；没有数据库变更。

## 涉及文件

后端：`runner_fabric` 的 router、schema、service、repository 及 `tests/test_runner_fabric.py`。
前端：`ExecutionFabricPage.tsx`、对应页面测试、`execution-fabric-service.ts`、`FabricInspection.tsx`、`use-fabric-polling.ts`。

## 针对性验证

- `make test-backend-targeted TARGETS='["tests/test_runner_fabric.py"]'`：35 项通过。新增全量 150 排队任务、真实任务分页、Pool 101、精确详情、非管理员拒绝和共享 Pool 跨组织事件隔离。
- `make test-frontend-targeted TARGETS='["src/pages/ExecutionFabricPage.test.tsx"]'`：9 项通过。覆盖服务端 150 聚合、Pool 第 6 页、页外精确任务、多 Lease/Fence、刷新失败保留数据、旧 Lease 有效性降级、跨组织迟到结果隔离、15 秒可见页刷新/隐藏暂停和关闭态。
- 受影响文件 Ruff、ESLint、Prettier、TypeScript 检查与 `mypy app` 通过。
- 完整原始日志保留在本工作树 `output/validation/m25-execution-fabric/`（未提交生成物）。
- 独立只读子审指出的缓存 Lease 刷新失败仍称有效问题已整改；未改变任何重试、超时或覆盖率门槛。

## 条件环境与验收边界

真实动态 GUI、Runner 心跳/故障转移、完整 `make check`、Compose 端到端、正式最新提交门禁、合并后 CI 和发布验收尚未执行，由整合负责人分别记账。当前 targeted 通过不代表这些验收通过。

验收负责人可在隔离数据库启用 `runner_fabric`，使用 `/tmp/flowtest-m25-isolated-fixture.py --project-id <已有测试项目> --admin-id <管理员>` 准备夹具；该脚本仅已做语法检查，尚未运行。项目需有一条已有执行，以使用合法外键。脚本创建独有 `audit-m25-*` 标签、101 个停用 Pool、一个没有令牌的离线 Runner、150 个未来可用且要求不存在能力的合成任务，以及一个包含过期/当前 Fence 的只读合成任务。执行记录为取消态；不调用执行、令牌或 Runner 状态接口。禁止在共享验收或用户数据库中直接运行。

在同一组织管理员会话中核对全量聚合 150、Pool 翻至第 6 页、`/execution-fabric?task=<返回ID>` 的多 Lease 和来源入口、隐藏/显示页面轮询及只读刷新；再切其他组织确认精确任务拒绝、切普通角色确认不读取管理目录。若已有其他任务，聚合应按夹具增量核对，而非假定总数恰为 150。合成任务不会产生真实报告，来源入口缺证据应按真实状态反馈。
