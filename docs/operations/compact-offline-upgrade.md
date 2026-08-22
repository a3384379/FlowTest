# Compact 离线升级与自动回滚值守

本文用于公司内网 Compact 的离线维护窗口。升级前必须停止业务写入，并确认旧安装目录、
`FLOWTEST_DATA_ENCRYPTION_KEY` 和备份目标均可用；自动回滚不替代变更审批。

## 执行升级

将新包解压到新目录，不覆盖旧目录：

```bash
cd /opt/flowtest-compact-4.0.1-arm64
./deploy/compact/upgrade_offline.sh \
  /opt/flowtest-compact-4.0.0-arm64/deploy/compact \
  /srv/flowtest-backups/pre-upgrade-4.0.1 \
  /srv/flowtest-evidence/upgrade-4.0.1.json
```

脚本按固定顺序校验新包、导入镜像、使用旧部署配置生成 PostgreSQL + MinIO 一致性备份、
启动新镜像并验证 6 服务 Readiness。不要在脚本运行时修改 `.env`、镜像清单、数据卷或备份目录。

## 判断结果

| 命令与证据 | 含义 | 运维动作 |
|---|---|---|
| 退出 0，`status=passed` | 新版本健康，新目录已取得 `0600` 的原 `.env` | 完成业务 smoke 后切换公司维护的 `current` 链接 |
| 退出非零，`status=rolled_back` | 升级失败，但旧数据、Artifact 和镜像已恢复 | 保持旧目录活动，记录失败原因，不得宣布升级成功 |
| 退出非零，`status=rollback_failed` | 新版本和自动恢复均失败 | 立即停止写入，按证据旁的备份目录手工执行旧版 `restore.sh` |

证据只记录固定状态、失败阶段、时间和新旧版本元数据，不记录目录、部署配置或凭据。
`rolled_back` 是恢复成功，不是升级成功；监控平台不得只按“服务当前健康”把它改判为通过。

## 成功后的活动目录

升级工具不会修改 `/opt/flowtest-current` 等公司符号链接。业务 smoke 通过后由变更负责人切换链接，
并保留旧目录和升级前备份直至观察窗口结束。新目录预先存在 `.env` 时脚本会拒绝升级，避免把另一环境的
加密密钥、数据库口令或管理员凭据带入当前数据卷。

失败升级不会在新目录留下 `.env`。自动回滚失败时，不得仅把链接或镜像改回旧版本；必须同时使用
升级前备份恢复 PostgreSQL 和 MinIO，并重新执行 `verify.sh` 和核心业务 smoke。
