# 升级与回滚

## 升级

1. 阅读 PR 的迁移、风险和回滚说明，并创建备份及隔离恢复验证。
2. 拉取目标标签并构建镜像，例如：`git checkout v2.0.0 && docker compose build`。
3. 停止 Worker 与 Beat，等待在途执行结束或取消。
4. 运行 `docker compose up -d --wait`；Backend 启动前自动执行 `alembic upgrade head`。
5. 运行 readiness、指标、容量门槛和 S3–S11 冒烟。

## 回滚

1. 停止写入和后台任务，记录失败版本、当前 Alembic revision 和异常日志。
2. 若迁移已提交且目标旧版本不兼容，使用当前代码执行对应 `alembic downgrade <revision>`。
3. 切换上一稳定标签并重建启动。
4. 若数据迁移不可逆或校验失败，按备份手册恢复整个 PostgreSQL + MinIO 恢复点。
5. 验证 readiness、核心业务链路和报告下载后再恢复流量。

V1.0 的 `20260809_0010`、S14 的 `20260809_0011`、S15 的 `20260810_0012`、S17 的 `20260810_0013`、S18 的 `20260811_0014`、S19 的 `20260811_0015`、S20 的 `20260811_0016/0017` 与 S21 的 `20260812_0018` 迁移均包含 downgrade；正式回滚仍必须先备份当前状态。

S16 不新增数据库迁移，数据库仍停留在 `20260810_0012`。回滚到 v1.1.0 不需要执行 Alembic downgrade；停止新执行并切换镜像即可。已创建的 SubFlow/ForEach 草稿或发布版本使用旧应用无法编辑或执行，回滚前应导出这些定义，回升 v1.5.0 后可继续使用；既有 V1 Execution、Snapshot 和报告不受影响。

## S14 / 0011 特别说明

- 升级会创建 `teams`、`team_members`、`project_team_grants`，并为 `api_versions` 增加提取和断言 JSON 列。
- 升级后必须执行 `alembic check`；该检查会比较服务器默认值，防止非空时间戳列在 PostgreSQL 实际写入时失败。
- 回滚到 0010 会删除团队与团队授权数据，并删除 API 版本中的提取/断言配置，执行前必须备份。
- 0010 不能表示 HAR、cURL、Bruno、Excel 来源标签；downgrade 会把这些 `import_runs.source_type` 映射为 `postman`。已归一化的 Diff/结果仍保留，但原始来源类型信息会丢失。
- 若上述数据必须无损保留，不执行数据库 downgrade；恢复上一份 PostgreSQL + MinIO 隔离验证通过的备份。

## S15 / 0012 特别说明

- 升级会创建 `test_cases`、`test_case_versions`、`test_suites`、`test_suite_versions` 和套件版本项，并为 Test Plan/Run Item 增加通用目标与固定快照字段。
- 升级会把现有 Test Plan Item 原地回填为 `target_type=workflow`，复用原 `workflow_id/workflow_version`，因此 V1 计划、CI Token、执行与报告保持兼容。
- 回滚到 0011 会删除全部 Case/Suite 资产和版本；由于 0011 无法表达 Case/Suite 计划项，downgrade 会先删除这些计划项，再恢复 Workflow 专用列为非空。
- 回滚前必须确认每个 Test Plan 至少保留一个 Workflow 项；若需无损保留 Case/Suite 或固定目标快照，不执行 downgrade，改用升级前 PostgreSQL + MinIO 备份恢复。

## S19 / 0015 特别说明

- 升级会创建 Quality Gate、Flaky Record 和 Gate Evaluation，并为 Project、Test Plan、Run 与 Run Item 增加配额、Cron、队列、基线和隔离字段；现有计划继续按手动或原固定间隔运行。
- 回滚到 0014 会删除全部门禁、Flaky 与 Evaluation 数据，并移除 Cron、时区、队列优先级和项目配额配置；运行及报告主体保留。
- 回滚前必须停止 Beat 和三个 Worker，防止旧代码在迁移过程中领取计划；迁移完成后再以目标版本重启。

## S21 / 0018 特别说明

- 升级会为 Project 增加默认关闭的样本共享开关，并创建 AI Job 与 Suggestion 表；现有 V1/V2 资产、执行、CI Token、Snapshot 和报告不变。
- 回滚到 `20260811_0017` 会删除全部 AI Job、Suggestion、Token 用量和审核结果；先导出审计证据并停止 AI Worker。
- AI 默认关闭，因此数据库升级本身不会向任何外部网关发送数据。回滚应用代码前应先关闭 Feature Flag，防止旧 Worker 在迁移窗口领取任务。

## S28 / 0025 特别说明

- 升级会创建 `impact_asset_mappings`、`impact_runs`、`test_selections` 和 `coverage_snapshots`；现有测试
  资产、契约、性能场景、执行和报告不变，Feature Flag 默认关闭。
- 回滚前先关闭 `FLOWTEST_FEATURE_IMPACT_ENGINE_ENABLED` 并停止新分析。降级到 `20260812_0024`
  会删除全部 Mapping、Impact Run、Test Selection、Coverage Snapshot、解释边、Gap 与 Fingerprint。
- 若这些影响分析证据必须保留，降级前应导出对应项目的运行结果；需要数据库级无损恢复时使用升级前
  PostgreSQL + MinIO 恢复点，而不是执行 destructive downgrade。
