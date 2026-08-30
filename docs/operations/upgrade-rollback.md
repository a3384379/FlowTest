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

V6 H1 开始，新写入或完成轮换的受管密文使用 `FTK1` 密钥引用包络，旧版应用无法读取。
`20260830_0049` 的 downgrade 会在任一受管表存在该包络时明确拒绝，不会伪装成可用回滚。
此时必须保留当前应用，或恢复经验证的升级前 PostgreSQL + MinIO 一致恢复点；不得强行切换旧镜像。

V1.0 的 `20260809_0010`、S14 的 `20260809_0011`、S15 的 `20260810_0012`、S17 的 `20260810_0013`、S18 的 `20260811_0014`、S19 的 `20260811_0015`、S20 的 `20260811_0016/0017` 与 S21 的 `20260812_0018` 迁移均包含 downgrade；正式回滚仍必须先备份当前状态。

S16 不新增数据库迁移，数据库仍停留在 `20260810_0012`。回滚到 v1.1.0 不需要执行 Alembic downgrade；停止新执行并切换镜像即可。已创建的 SubFlow/ForEach 草稿或发布版本使用旧应用无法编辑或执行，回滚前应导出这些定义，回升 v1.5.0 后可继续使用；既有 V1 Execution、Snapshot 和报告不受影响。

## V2 RC ↔ V3 原地升级与回滚演练

V2 基线固定为 `v2.0.0-rc.1@06699d54bceee091a2efac838e426cf7ef5c9c9e`，数据库 revision
为 `20260812_0018`；当前 V3 S31 revision 为 `20260813_0028`。可在仓库根目录执行：

```bash
scripts/verify_v2_v3_upgrade.sh
```

脚本会校验 V2 tag 对应的精确 commit，然后在独立 Compose Project、随机本机端口和
三个专用数据卷中自动执行：

1. 使用 V2 镜像在 `0018` 创建 Project、Environment、API、Workflow、Execution 和 Report。
2. 导出 PostgreSQL custom-format 安全检查点，并生成 MinIO SHA-256 清单。
3. 使用当前代码原地升级到 `0028`，执行 `alembic check`，校验旧资产并再运行。
4. 使用当前代码降级到 `0018`，切回 V2 应用，再次校验和执行。
5. 重新升级到 `0028`，再次执行 `alembic check`、旧资产执行与 MinIO 哈希校验。

每次退出都会删除该次演练的容器、卷、临时源码和临时镜像，不读写开发环境的
PostgreSQL/MinIO 数据卷。脚本只用于 CI 和发布演练，不是生产环境的一键升级器。

`0028 → 0018` 是 destructive downgrade：S22–S31 新增的 Capability、Schema、Performance、
Environment、Contract、Impact、Runner、Failure Intelligence 和 Release Gate 数据都会被删除。
演练会特意创建一条 V3 Release Policy，并在重新升级后确认它已被回滚删除，同时
V2 业务资产仍完整。需保留 V3 证据时不得执行此 downgrade，应使用升级前已验证的
PostgreSQL + MinIO 恢复点。

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

## S29 / 0026 特别说明

- 升级会扩展 `runner_pools` / `runners` Profile，为 Project 增加执行并发和排队上限，并创建
  `runner_registration_tokens`、`runner_tasks`、`runner_leases` 和 `runner_events`。现有项目、
  Workflow、Execution 和 Celery 执行保持兼容，Runner Fabric Feature Flag 默认关闭。
- 启用 Feature Flag 前先完成 `alembic upgrade 20260812_0026` 与 `alembic check`，再创建 Pool、
  注册 Runner。从 Celery 执行切换时应先停止新 Workflow 投递，等旧 Worker 在途执行终态后
  再开启 Flag，避免在切换窗口人工重复发起同一业务测试。
- 应用镜像回滚前先 Drain 所有 Runner，等待 `flowtest_runner_active_leases=0`，然后关闭
  `FLOWTEST_FEATURE_RUNNER_FABRIC_ENABLED` 并停止 Agent 与 Beat。不得在 Active Lease 存在时直接降级。
- 降级到 `20260812_0025` 会删除全部 Runner 注册、Task、Lease、Fence 和 Event 证据，并移除
  Runner Token Hash 与 Project 容量字段。降级前必须导出审计事件，并吊销所有远程明文
  Token；旧 Token 不得在回升后复用。
- 若需保留分布式执行审计或当时仍有排队任务，不执行 destructive downgrade；使用升级前已验证的
  PostgreSQL + MinIO 恢复点，并重新签发所有 Runner 身份。

## S30–S31 / 0027–0028 特别说明

- 降级到 `20260812_0026` 会删除 Failure Cluster、Regression Baseline、Release Risk、AI Draft
  Change Set 及其审核证据；降级前先关闭 Quality Intelligence 与 AI，并停止 AI Worker。
- 降级到 `20260813_0027` 会删除 Release Policy 和不可变 Release Decision Snapshot。这些
  是发布判断的历史证据，需要保留时必须使用完整恢复点，不得以当前页面重算代替。

## V5 S37–S45 / 0033–0040 特别说明

- S37–S45 的当前迁移 head 为 `20260823_0040`；升级前必须停止 Worker/Beat 和新的执行提交，
  保存 PostgreSQL custom dump、MinIO 对象 SHA-256 清单、当前 Runtime Profile 和镜像摘要。
- 从 `20260822_0039` 升级到 `20260823_0040` 会创建 Change-Aware Regression 的运行/阶段记录，
  并扩展 AI ChangeSet 的 `source_type` 约束；既有 Project、Workflow、Execution、Artifact、Evidence、
  MCP 和组织数据保持可读取。
- `20260823_0040 → 20260822_0039` 会删除 S45 回归运行、阶段、证据和缺失测试关联记录。需要保留
  这些发布证据时不得执行数据库 downgrade，应恢复升级前完整 PostgreSQL + MinIO 一致性备份。
- 若只切换旧镜像而不处理数据库 revision，旧应用可能无法理解新表或 ChangeSet 来源；禁止把切换镜像
  当作回滚完成。回滚后必须再次执行 `/api/v1/ready`、`/api/v1/runtime-profile`、旧项目资产读取、
  Artifact 下载和一条无副作用的执行/证据查询。
- Standalone 使用显式 `20260823_0040` metadata/bootstrap 基线；Standalone 与 Compact 之间只通过
  `standalone-compact-transfer-v1` 导出/导入，不复制 SQLite 文件。Transfer 表清单和数据分类必须与
  [S46 兼容矩阵](../release/s46-compatibility-matrix.md)一致。
- 每次迁移演练都必须执行 `upgrade → alembic check → downgrade -1 → upgrade → alembic check`，
  并清理明确命名的临时数据库、容器和卷；不得触碰开发环境现有 Compact 数据卷。
