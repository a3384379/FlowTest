# 备份、恢复与演练

## 创建一致恢复点

备份期间应暂停新执行或安排维护窗口，确保 PostgreSQL 元数据和 MinIO 对象处于同一业务恢复点。

```bash
backup_directory="$(mktemp -d)"
scripts/backup.sh "${backup_directory}"
```

产物包括 PostgreSQL custom dump、MinIO 对象、版本化 Manifest、每个对象的 SHA-256 和源提交。
备份系统还必须独立保存 `FLOWTEST_DATA_ENCRYPTION_KEY`；缺失该密钥时 Secret、计划和通知配置无法解密。

## 隔离恢复验证

```bash
scripts/verify_restore.sh "${backup_directory}"
```

脚本创建临时网络、PostgreSQL 卷和 MinIO 卷，恢复后检查 Alembic 版本、用户表和所有对象哈希，
最后删除临时容器、网络与卷，不接触当前 FlowTest 数据。

## 正式恢复

正式恢复会覆盖当前数据库和 Bucket，必须明确确认：

```bash
FLOWTEST_RESTORE_CONFIRM=RESTORE scripts/restore.sh "/absolute/path/to/backup"
```

恢复顺序为停止 API/Worker/Beat、重建 PostgreSQL 数据库、恢复 MinIO、重新启动并等待健康检查。
恢复后立即执行 S11 冒烟，并核对最新项目、执行、报告和附件。
