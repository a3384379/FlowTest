# FlowTest Compact 离线安装包

该包包含单一 Docker 架构的 5 个镜像和 6 服务 Compact 编排，不包含任何密码、
Secret 或业务备份。安装服务器不需要 Git、Python、Node.js 或外网连接。

## 完整性校验

将压缩包复制到目标机后，先从与制品不同的公司受信发布渠道取得 `.sha256`，
再使用 OpenSSL 核对压缩包摘要并解压。不要跳过这一步；从同一未受信位置同时取得制品和摘要不能证明发布者身份。

```bash
openssl dgst -sha256 flowtest-compact-*.tar.gz
cat flowtest-compact-*.tar.gz.sha256
tar -xzf flowtest-compact-*.tar.gz
cd flowtest-compact-*/
```

## 首次安装

```bash
./deploy/compact/install_offline.sh
```

安装器会再次校验包内每个文件、加载 `images.tar`、比对每个镜像 ID 和架构，
然后生成权限为 `0600` 的 `.env` 并以 `--pull never --no-build` 启动。默认访问地址为
<http://localhost:3000>，管理员密码仅在 `deploy/compact/.env` 中。

## 无外网升级

解压新版本到新目录，不要覆盖旧目录。传入旧版 `deploy/compact` 目录、一个
不存在的绝对备份路径，并可指定机器可读证据路径：

```bash
./deploy/compact/upgrade_offline.sh \
  /opt/flowtest-compact-current/deploy/compact \
  /srv/flowtest-backups/pre-upgrade-4.0 \
  /srv/flowtest-evidence/upgrade-4.0.json
```

脚本会先校验并导入新镜像，再使用旧版工具生成 PostgreSQL + MinIO 一致性备份，
最后将同一 Compose Project 切换到新镜像并执行 Alembic 迁移。新版本未通过启动或 Readiness 时，
脚本会自动使用旧目录的镜像和升级前备份覆盖恢复 PostgreSQL/MinIO，并以非零状态退出；
`status=rolled_back` 只表示旧版本已恢复，不表示升级成功。

正常升级会把旧安装的 `.env` 以 `0600` 复制到新目录，使新目录成为完整活动安装；工具不会修改
公司维护的 `current` 符号链接。失败升级不会复制 `.env`。如果自动回滚证据为
`rollback_failed`，必须立即停止写入并按控制台路径手工恢复，不得只切换旧镜像。

## 从 Windows Standalone 导入

使用 Standalone 包中的 `export-to-compact.ps1` 生成传输包后，将其复制到本机并确认 Compact
`.env` 的 `FLOWTEST_DATA_ENCRYPTION_KEY` 与源环境相同，再运行：

```bash
FLOWTEST_IMPORT_CONFIRM=IMPORT_STANDALONE \
  ./deploy/compact/import-standalone.sh /srv/flowtest-transfer/standalone-to-compact
```

脚本会先为 PostgreSQL 初始化 Alembic Schema，目标业务表必须为空；随后校验传输包、导入 PostgreSQL、
上传 MinIO 并执行 Readiness。登录会话、OIDC 事务、通知重试和 Runner 临时状态不会迁移。

## 长时健康观察

```bash
FLOWTEST_S34_SOAK_DURATION_SECONDS=259200 \
  ./deploy/compact/soak.sh /srv/flowtest-evidence/compact-72h.json
```

观察期间不要重启容器或清空 Redis。证据同时记录 Readiness 失败、P95、最长连续失败、
容器重启及期末队列积压。

## 隐私安全诊断与回滚演练

遇到安装或运行问题时，先生成本地诊断目录：

```bash
./deploy/compact/collect_support_bundle.sh \
  /srv/flowtest-evidence/support-2026-08-19
```

诊断目录使用文件白名单，只收集公开健康响应、版本、容器状态、资源上限和基础设施聚合值；
不收集部署配置、容器环境、原始日志、对象名称/内容或业务明细。工具会校验逐文件 SHA-256，
但不会自动上传；发送前仍须人工检查。

试点或升级前可在审批窗口执行真实回滚演练。该操作会两次短暂停服并覆盖恢复当前数据，
最终回到演练前恢复点：

```bash
./deploy/compact/drill_rollback.sh \
  /srv/flowtest-backups/rollback-drill \
  /srv/flowtest-evidence/rollback-drill.json
```

脚本先建立 PostgreSQL + MinIO 一致性备份，再写入一次性 Project/Artifact、恢复并确认其消失，
随后验证恢复后仍可写入，再次恢复基线。保留的备份和证据不包含 `.env`；加密密钥仍须独立托管。
