# FlowTest 小型化部署

Compact 是 V4 S32～S36 面向公司内网试用和功能测试的单机档位。它保留与 Full 相同的 API、
PostgreSQL 数据模型、Alembic 迁移和 MinIO Artifact 格式，只缩减运行拓扑，不建立第二套产品行为。

从 GitHub 克隆到公司电脑、Windows/WSL2 注意事项、首次登录和日常运维的完整步骤见
[`docs/operations/compact-company-quickstart.md`](../../docs/operations/compact-company-quickstart.md)。

## 资源与边界

- 建议主机：2 CPU、4 GB 内存、10 GB 以上可用磁盘，支持 ARM64 和 x86_64。
  2026-08-19 ARM64 本机验收的 6 容器空闲内存合计约 918 MiB，容器上限合计约 2.6 GiB。
- 固定 6 个服务：Web、API、合并 Worker/Beat、PostgreSQL、Redis、MinIO。
- Worker 并发默认 2；General、Data、AI 等安全队列由同一进程消费。
- 不内置 Redpanda、Mock 目标、可观测性套件、k6 Worker、Environment DinD 或本地 Runner Agent。
- Performance Lab 和 Environment Lab 在 Compact 中固定关闭，误开会被应用启动校验拒绝。
- Kafka/WebSocket 能力可连接公司已审批的外部目标，但 Compact 不提供测试 Broker。

Compact 适合部门试用、小团队回归和 CI 功能验证，不替代 Full 档位的性能容量、Worker 故障隔离、
PITR、Environment Lab 与完整发布验收。

## 一键启动

源码启动需要 Docker Engine/Desktop、Compose v2、OpenSSL 和 Curl；首次构建还需要访问 Docker Hub
和项目依赖源：

```bash
git clone --branch main --single-branch https://github.com/a3384379/FlowTest.git
cd FlowTest
./deploy/compact/start.sh
./deploy/compact/verify.sh
```

脚本首次运行会生成 `deploy/compact/.env`，权限为 `0600`，其中包含随机管理员密码和随机服务密钥；
已有文件绝不会被覆盖。启动完成后访问 <http://localhost:3000>，管理员邮箱默认为
`admin@flowtest.dev`。登录页面的账号字段同时接受邮箱和 `admin` 别名；`admin` 会解析到配置的
`FLOWTEST_BOOTSTRAP_ADMIN_EMAIL`。密码仍以本机 `.env` 中的
`FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD` 为准，Compact 首次登录后需要修改密码。不要复制密码到聊天、工单
或部署日志。登录后如果账号没有项目，质量总览和项目管理页会显示“创建第一个项目”入口。
源码构建使用独立 `compose.build.yaml`；当同目录存在 `images.env` 时，`start.sh` 会自动改为
不构建、不拉取的镜像部署模式。

默认只监听 `127.0.0.1`。需要供内网用户访问时，将 `FLOWTEST_BIND_ADDRESS` 改为服务器的受控内网 IP，
并将 `FLOWTEST_PUBLIC_ORIGIN` 改为最终访问 Origin；跨主机或长期使用应在外层接入 TLS，再启用
`FLOWTEST_SECURE_COOKIES=true`。不要直接向公网开放 Compact 端口。

## 验证与日常操作

```bash
./deploy/compact/verify.sh
docker compose --env-file deploy/compact/.env -f deploy/compact/compose.yaml ps
docker compose --env-file deploy/compact/.env -f deploy/compact/compose.yaml logs --tail=200 backend worker
docker compose --env-file deploy/compact/.env -f deploy/compact/compose.yaml stop
```

验收脚本要求恰好 6 个服务运行，并通过 PostgreSQL、Redis、MinIO Readiness 以及 `compact` 运行档位检查。
独立 CI 还会执行 `scripts/smoke_s32.py`，覆盖真实登录、API/Workflow 发布、合并 Worker 执行和
不可变 Snapshot。
日常停止不要添加 `--volumes`，否则会删除业务数据。

## 私有仓库与离线包

发布工作站先完成公司规定的 `docker login`，再把 5 个唯一镜像推送到私有仓库。
脚本输出的是仓库返回的不可变 Digest，不是 Tag：

```bash
./deploy/compact/publish_private_registry.sh \
  registry.example.com/testing/flowtest 4.0.0 \
  /srv/flowtest-release/images.env
```

将输出文件审批后放到 `deploy/compact/images.env`，运行 `start.sh` 即可只使用摘要锁定的私有镜像。
脚本不接收仓库密码，也不把 Docker Credential 写入配置或镜像。
私有仓库 Tag 会自动带 `-amd64` 或 `-arm64`，每个架构分别发布；最终部署仍使用与 Tag 无关的不可变 Digest。

完全无外网环境按目标 Docker 架构生成单架构包：

```bash
./deploy/compact/export_offline_bundle.sh \
  /srv/flowtest-release/flowtest-compact-4.0.0-arm64.tar.gz 4.0.0
```

压缩包包含 5 个镜像、镜像 ID/平台清单、逐文件 SHA-256 和安装/升级/备份脚本，
不包含 `.env` 或业务数据。请通过独立受信渠道发布同名 `.sha256`。解压后执行：

```bash
./deploy/compact/install_offline.sh
```

安装器会检查包内每个文件和镜像架构，然后以 `--pull never --no-build` 启动。
无外网升级命令与回滚规则见包内 `README.md`。
正式制品默认拒绝未提交源码；`FLOWTEST_ALLOW_DIRTY_RELEASE=1` 仅用于本地开发演练，
产生的 `SOURCE_STATE=dirty` 包不得进入公司环境。

## 备份与恢复

Compact 备份工具只依赖 Docker，会短暂停止 Web、API 和 Worker，以取得 PostgreSQL 与 MinIO
的同一业务恢复点。备份目标必须是不存在的绝对路径，脚本不会覆盖旧备份：

```bash
./deploy/compact/backup.sh /srv/flowtest-backups/2026-08-19
FLOWTEST_RESTORE_CONFIRM=RESTORE \
  ./deploy/compact/restore.sh /srv/flowtest-backups/2026-08-19
```

恢复在停服和覆盖前会先执行 `pg_restore --list`，并校验每个 Artifact 的文件名、大小和
SHA-256；恢复后再比对远程对象集与 Readiness。备份不包含 `.env`，必须把
`FLOWTEST_DATA_ENCRYPTION_KEY` 与备份分开托管，否则恢复后无法解密 Secret 和执行计划。

### 从 Standalone 导入

Standalone 使用 SQLite，不能把 `data/flowtest.db` 直接复制到 Compact。请在 Windows 云桌面先运行
`deploy/standalone/export-to-compact.ps1` 生成 `standalone-compact-transfer-v1` 传输包，再通过公司
批准的安全渠道复制到 Compact 主机。导入前必须将 Compact `.env` 中的
`FLOWTEST_DATA_ENCRYPTION_KEY` 设置为 Standalone 的同一值；该密钥不进入传输包，也不要放在命令行：

```bash
FLOWTEST_IMPORT_CONFIRM=IMPORT_STANDALONE \
  ./deploy/compact/import-standalone.sh /srv/flowtest-transfer/standalone-to-compact
```

脚本会在导入前启动 PostgreSQL/Redis/MinIO 并运行 Alembic；随后只接受 `20260821_0029`、业务表为空的
目标数据库，先校验逐表 JSONL、外键关系和 Artifact SHA-256，再导入 PostgreSQL 并上传 MinIO。失败会回滚数据库并清理由本次导入新上传的对象；
非空目标、版本不匹配、同名对象内容不同或传输包篡改都会拒绝。登录会话、OIDC 事务、通知重试、Runner
租约/任务等运行状态不会迁移，导入完成后需重新登录并重新建立这些运行状态。

## S34 容量、稳定性与档位兼容

源码验收工作站可生成可机器读取的 API/Workflow 容量证据和 Full↔Compact 双向资产证据：

```bash
./deploy/compact/benchmark.sh /srv/flowtest-evidence/compact-capacity.json
./deploy/compact/verify_profile_compatibility.sh \
  /srv/flowtest-evidence/full-compact-compatibility.json
```

长时观察可直接在离线安装目录运行：

```bash
FLOWTEST_S34_SOAK_DURATION_SECONDS=259200 \
  ./deploy/compact/soak.sh /srv/flowtest-evidence/compact-72h.json
```

双向兼容工具会在同一数据卷上临时将合并 Worker/Beat 切换为分离 Worker/Beat，分别创建并反向读取
Project、Artifact、Workflow Version 和 Execution Snapshot。这是同版本数据契约验收，不代替 Full 完整容量和实验室验收。
公司试点步骤、72 小时观察和人工签署见
[`docs/operations/compact-pilot.md`](../../docs/operations/compact-pilot.md)。

## S35 诊断包与回滚证明

部署异常时生成一个不存在的绝对目录：

```bash
./deploy/compact/collect_support_bundle.sh \
  /srv/flowtest-evidence/support-2026-08-19
```

诊断目录固定使用文件白名单，只包含公开健康响应、运行档位、镜像引用、容器状态/重启次数、
资源上限、Alembic 版本、数据库容量、队列深度及对象数量/总字节数。它明确不包含 `.env`、
容器环境、原始日志、请求/响应正文、对象名称/内容或项目名称；每个探针的退出码会单独记录，
因此服务已经降级时也能生成可核验的部分证据。脚本完成后会执行文件白名单、敏感字段和逐文件
SHA-256 校验，但不会自动上传。发送前仍须由公司运维或安全负责人检查。

试点和升级前可在审批窗口执行真实回滚演练：

```bash
./deploy/compact/drill_rollback.sh \
  /srv/flowtest-backups/rollback-drill \
  /srv/flowtest-evidence/rollback-drill.json
```

演练会建立一致性备份，写入一次性 Project/Artifact，恢复后确认该写入消失；随后再验证恢复后
仍可写入并再次恢复，最终回到演练前基线。该命令会两次短暂停服和覆盖数据，只能在已审批的
维护窗口运行；自动恢复失败时必须使用脚本保留的备份立即手工恢复。

## 配置与升级原则

- `FLOWTEST_WORKER_CONCURRENCY` 可在 1～4 之间调整；超过 2 前应先确认主机余量。
- MinIO API 仅绑定宿主 `127.0.0.1:9000`，用于后续备份工具接入，不开放 Console。
- 启用 AI 时仍必须配置 HTTPS 网关、模型与 API Key；AI 任务复用合并 Worker。
- 正式公司部署优先使用已审批的私有仓库 Digest 或已校验离线包；源码构建用于开发。
- 升级继续执行同一 Alembic 链。任何升级前都必须同时备份 PostgreSQL、MinIO 和
  `FLOWTEST_DATA_ENCRYPTION_KEY`，不得只复制数据库卷。
- 离线升级会生成 `passed`、`rolled_back` 或 `rollback_failed` 证据。启动/Readiness 失败会自动
  使用旧镜像与一致性备份恢复，但命令仍返回非零；只有 `passed` 才能切换公司维护的活动目录链接。
- 升级成功后，新目录取得权限为 `0600` 的原 `.env`；失败时不复制凭据。新目录预先存在另一份
  `.env` 会被拒绝，避免混用加密密钥或数据库口令。

维护窗口的状态判定、活动目录切换和 `rollback_failed` 处置见
[`docs/operations/compact-offline-upgrade.md`](../../docs/operations/compact-offline-upgrade.md)。
