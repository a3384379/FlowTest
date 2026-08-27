# Compact 诊断与回滚值守

本文用于公司内网 Compact 试点的故障交接。诊断工具只生成本地文件，不连接工单、邮件或外部上传端点。

## 收集诊断证据

在部署目录运行：

```bash
./deploy/compact/collect_support_bundle.sh \
  /srv/flowtest-evidence/support-2026-08-19T1200
```

服务健康时，`PROBE_STATUS.tsv` 的探针退出码应全部为 `0`。服务降级时脚本仍会保留固定文件集，
失败探针对应文件可能为空，以退出码表达不可用，不会退化成抓取原始日志或容器环境。

允许收集的字段只有：

- 公开 `/live`、`/ready`、`/runtime-profile` 响应；
- Docker 架构/容量、Compose 版本、源码版本和 dirty/clean 状态；
- 6 个固定服务的容器 ID、镜像、状态、健康、重启次数及资源上限；
- Alembic Head、数据库字节数/连接数、Redis 内存、固定队列深度；
- MinIO 对象总数和总字节数，不包含对象 Key、名称或内容。

目录不得添加 `.env`、`images.env`、容器 Inspect 全量输出、原始日志、数据库 Dump、截图或业务导出。
`verify_support_bundle.sh` 会拒绝未登记文件、符号链接、摘要不一致和已知凭据字段。发送前仍须逐文件检查，
只通过公司批准的工单或文件交换渠道交接。

## 执行回滚演练

回滚演练是有意的数据覆盖操作，只能在已通知用户、停止业务写入并批准维护窗口后运行：

```bash
./deploy/compact/drill_rollback.sh \
  /srv/flowtest-backups/rollback-drill-2026-08-19 \
  /srv/flowtest-evidence/rollback-drill-2026-08-19.json
```

工具依次完成：一致性备份、一次性 Project/Artifact 写入、覆盖恢复和缺失验证、恢复后再次写入、
第二次覆盖恢复及最终 Readiness。正常退出后业务数据回到演练前恢复点；备份继续保留，便于人工抽检。
如果演练中断，退出处理器会尝试恢复；自动恢复失败时停止所有写入，按控制台提示使用保留目录执行
`FLOWTEST_RESTORE_CONFIRM=RESTORE restore.sh`，不得删除备份或只切换旧镜像。

诊断包、回滚证据和短时自动化都不能代替 72 小时公司试点、业务负责人签署或正式 RC 门槛。
