# 升级与回滚

## 升级

1. 阅读 PR 的迁移、风险和回滚说明，并创建备份及隔离恢复验证。
2. 拉取目标标签并构建镜像：`git checkout v1.0.0 && docker compose build`。
3. 停止 Worker 与 Beat，等待在途执行结束或取消。
4. 运行 `docker compose up -d --wait`；Backend 启动前自动执行 `alembic upgrade head`。
5. 运行 readiness、指标、容量门槛和 S3–S11 冒烟。

## 回滚

1. 停止写入和后台任务，记录失败版本、当前 Alembic revision 和异常日志。
2. 若迁移已提交且目标旧版本不兼容，使用当前代码执行对应 `alembic downgrade <revision>`。
3. 切换上一稳定标签并重建启动。
4. 若数据迁移不可逆或校验失败，按备份手册恢复整个 PostgreSQL + MinIO 恢复点。
5. 验证 readiness、核心业务链路和报告下载后再恢复流量。

V1.0 的 `20260809_0010` 迁移包含完整 downgrade；正式回滚仍必须先备份当前状态。
