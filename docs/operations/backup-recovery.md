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

## 可选 WAL-G 时间点恢复（PITR）

逻辑备份用于完整迁移，PITR 用于恢复到误操作之前的具体时间，两者不能互相替代。PITR 默认关闭。
生产启用前必须替换示例加密密钥，并将 MinIO/S3、密钥和备份保留策略纳入独立灾备域：

```bash
export FLOWTEST_PITR_ENABLED=true
export FLOWTEST_PITR_ENCRYPTION_KEY="$(openssl rand -hex 32)"
docker compose up -d --build --wait postgres backend worker worker-data worker-ai beat
scripts/pitr_backup.sh
```

PostgreSQL 使用 `archive_mode=on` 和 WAL-G `archive_command` 连续归档 WAL。基础备份和 WAL 默认写入
`s3://flowtest-artifacts/pitr/postgres`，可使用 `WALG_S3_PREFIX` 指向独立 Bucket。加密密钥不得与备份
放在同一存储位置；丢失密钥会导致备份不可恢复。

发布前执行隔离 PITR 演练：

```bash
scripts/verify_pitr.sh
```

演练创建探针数据和基础备份，在目标时间后再写入一条记录，然后把备份与 WAL 恢复到独立 Docker 卷。
验收必须只看到目标时间之前的 marker。脚本不会挂载或覆盖当前 PostgreSQL 数据卷，结束时会删除
探针表、临时容器和显式命名的演练卷。失败时先检查 PostgreSQL `pg_stat_archiver`、MinIO 可用性、
WAL-G 加密密钥与 `WALG_S3_PREFIX` 是否和备份时一致。
