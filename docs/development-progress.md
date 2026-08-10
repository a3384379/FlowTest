# FlowTest 开发进度

最后更新：2026-08-11（Asia/Shanghai）  
状态：按用户要求暂停；不得开始 S20 或 V3，直至用户明确要求继续。

## 当前恢复点

- 基线：`main@8328081`（S18 已合并）。
- 当前分支：`agent/s19-quality-scale`。
- 当前提交：`6391c5b`。
- Draft PR：[GitHub #21](https://github.com/a3384379/FlowTest/pull/21)。
- S17 Draft PR #19 与 S18 PR #20 已合并；S19 已实现但尚未合并、尚未创建 `v1.8.0` 标签。
- S20、S21 与 V3 S22–S31 均未开始。
- `FlowTest_V3_UI_CN_HD/` 是用户提供的未跟踪原型资产，保持原样；计划在 S22 排除 `.DS_Store` 后纳入 Git。

## S19 已完成实现

1. Test Plan 支持五字段 Cron、IANA 时区、0～9 优先级，以及 `general`、`data`、`ai` 多队列。
2. 项目并发与排队配额使用 PostgreSQL 锁保证一致性；API 和 Worker 分离处理排队、延迟领取与取消。
3. Compose 提供 General、Data、AI 三类 Worker，并按目标类型路由任务。
4. Flaky 记录支持确定性聚合、隔离和固定到计划 Snapshot。
5. Quality Gate 覆盖通过率、失败数、Flaky、耗时基线回归与 Breaking Change；提供 CI Token 接口。
6. JUnit XML 导出、质量中心中文 UI、S19 冒烟与 Playwright 验收已实现。
7. Alembic `20260811_0015` 具备 upgrade/downgrade，并已完成真实 PostgreSQL 往返与漂移检查。
8. 真实容量脚本覆盖 100 个并发 Workflow 和停止 Worker 后持久化 1000 个排队任务。

## 已完成验证

- 后端：Ruff、mypy strict、依赖边界检查通过；175 项测试通过、3 项按环境跳过，总覆盖率 90.53%。
- 前端：94 项测试通过；Statements 83.24%、Branches 80.21%、Functions 81.26%、Lines 85.17%；构建通过。
- Playwright：S14–S19 与 V1 主路径共 7 项通过。
- 安全：前后端依赖审计无已知漏洞；上一完整提交的源代码和镜像扫描通过。
- API 稳态容量：本地三次 P95 均低于 0.5 秒；脚本增加连接池预热但没有放宽默认门槛。
- 100 Workflow：本地 100/100 通过，最近一次 P95 4.788 秒，无失败。
- 1000 排队任务：本地 1000/1000 到达终态，Run ID 与 Execution ID 均唯一，零失败、零重复终态，耗时 41.978 秒。
- Compose 全栈在暂停前健康；现已执行 `docker compose stop`，数据卷未删除。

## 暂停时的 CI 状态

用户要求暂停后，已主动取消 `6391c5b` 上仍运行的 Frontend、Security 与 Compose 工作流；Backend Test 与 Integration 已通过。取消是人为停止，不代表测试失败。

此前 `41af5c8` 的 Backend、Frontend、Integration 与 Security 均通过；Compose 已通过所有功能、浏览器和 100 Workflow 步骤，最后仅因 1000 任务入队客户端固定 30 秒超时而退出。`6391c5b` 已将该传输超时绑定到整体 900 秒容量窗口，并在本地完成上述 1000/1000 验证。

## 继续开发时的固定步骤

1. `git switch agent/s19-quality-scale`，确认 `git status` 仅包含用户原型目录。
2. `docker compose up -d --build --wait` 恢复本地服务。
3. 重新运行 PR #21 的 Backend、Frontend、Security 与 Compose 全量 CI，不使用被取消的结果代替。
4. 全绿后将 Draft PR 转为 Ready，squash 合并 `main`，删除迭代分支并创建、推送 `v1.8.0`。
5. 从更新后的 `main` 创建 `agent/s20-enterprise-observability`；S20 首项为 OIDC Code + PKCE、Vault KV v2、OpenTelemetry/Grafana 与可选 WAL-G PITR。
6. S20 完成并合并前，不开始 S21；S21 完成、V2 升级/回滚及真实 14 天 RC 达标前，不创建 `v2.0.0`，也不开始 S22。

## 已识别但未开始的 S20 接入点

- OIDC：新增一次性服务端登录事务，校验 state、nonce、PKCE、Issuer、Audience、签名、邮箱验证和允许域名；JIT 用户默认无项目权限，本地管理员登录保留。
- Vault：Credential 增加 `local`/`vault_kv_v2` Provider 元数据；Vault Secret 不落库、不从 API 返回。
- 可观测性：传播 W3C Trace Context，打通 API → Celery Worker → Workflow Node；补充队列和 Worker 指标及 Grafana 模板。
- PITR：提供可选 WAL-G Profile、备份/恢复脚本和隔离恢复演练，不能以现有逻辑备份冒充 PITR。
- CI：可在 S20 引入固定 SHA 的 Buildx/GHA Layer Cache，减少固定 Python 3.13.15 镜像从源码重复构建时间；该优化尚未写入代码。
