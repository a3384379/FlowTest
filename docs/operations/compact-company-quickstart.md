# 公司电脑 Compact 快速部署

本文面向需要在公司电脑下载、启动和测试 FlowTest 的使用者。Compact 固定运行 Web、API、
合并 Worker/Beat、PostgreSQL、Redis 和 MinIO 共 6 个容器，适合单机试用和功能验证。

## 先选择安装方式

| 公司电脑条件 | 安装方式 | 说明 |
|---|---|---|
| 可访问 GitHub、Docker Hub 和项目依赖源 | GitHub 源码启动 | 最适合开发和快速试用，首次启动会在本机构建镜像 |
| 只能访问公司私有镜像仓库 | 私有仓库 Digest | 由发布工作站推送 5 个镜像并交付 `images.env` |
| 完全不能访问外网或镜像仓库 | 单架构离线包 | 由受信发布工作站生成，目标机只加载本地镜像 |

GitHub 的 Source code ZIP/TAR 只包含源码，不包含 Docker 镜像，不能当作完全离线安装包。

## 电脑要求

- ARM64 或 x86_64 CPU，Docker 可用内存至少 3 GiB，建议 2 CPU、4 GB 内存和 10 GB 可用磁盘。
- Docker Engine/Desktop、Docker Compose v2、Git、Bash、OpenSSL 和 Curl。
- macOS/Linux 可直接使用终端。Windows 11 建议使用 WSL2 Ubuntu，并在 Docker Desktop 中启用对应
  WSL Distribution 的 Integration；仓库应克隆到 WSL 文件系统并从 WSL 终端执行脚本。
- 默认使用宿主端口 `3000` 和 `9000`。如被占用，应在首次启动前调整生成后的 `.env`，不要修改脚本。

先确认基础工具可用：

```bash
docker info
docker compose version
git --version
openssl version
curl --version
```

## 从 GitHub 下载并启动

正式试用应固定公司审批过的分支或版本标签。下面命令下载已经合并的 `main`：

```bash
git clone --branch main --single-branch https://github.com/a3384379/FlowTest.git
cd FlowTest
./deploy/compact/start.sh
./deploy/compact/verify.sh
```

`start.sh` 会执行安装前检查、首次构建、数据库迁移和 Readiness 验证。首次运行时间取决于公司网络和
Docker 镜像缓存。成功标准是 `verify.sh` 输出 6 个服务运行中，数据库、Redis 和对象存储均就绪。

首次启动会创建 `deploy/compact/.env`，权限为 `0600`，并写入随机管理员密码、JWT 密钥、
AES-256-GCM 数据加密密钥、数据库和对象存储凭据。脚本拒绝覆盖已有 `.env`；该文件已被 Git 忽略，
但仍应限制为部署管理员可读并纳入公司 Secret 托管，不得提交 Git、上传网盘或粘贴到工单。

浏览器访问 <http://localhost:3000>，使用管理员邮箱 `admin@flowtest.dev` 和本机 `.env` 中的
`FLOWTEST_BOOTSTRAP_ADMIN_PASSWORD` 登录，随后立即修改密码。

## 日常启停和检查

在仓库根目录执行：

```bash
./deploy/compact/start.sh
./deploy/compact/verify.sh
docker compose --env-file deploy/compact/.env -f deploy/compact/compose.yaml ps
docker compose --env-file deploy/compact/.env -f deploy/compact/compose.yaml logs --tail=200 backend worker
docker compose --env-file deploy/compact/.env -f deploy/compact/compose.yaml stop
```

不要使用 `docker compose down --volumes`，它会删除 PostgreSQL、Redis 和 MinIO 数据卷。
诊断日志可能包含业务错误上下文，只能进入公司批准的受限渠道；提交问题前优先按
[`compact-support.md`](compact-support.md) 生成隐私安全诊断包。

## 允许其他内网电脑访问

默认仅监听 `127.0.0.1`。需要开放给受控公司网段时，先停止服务，再修改 `deploy/compact/.env`：

```dotenv
FLOWTEST_BIND_ADDRESS=10.0.0.20
FLOWTEST_PUBLIC_ORIGIN=https://flowtest.intra.example.com
FLOWTEST_SECURE_COOKIES=true
```

将示例 IP、Origin 替换为公司审批值，并由外层反向代理终止 TLS、限制来源网段。不要把 Compact
端口直接开放到公网；修改后重新运行 `start.sh` 和 `verify.sh`。

## 备份与升级

业务数据存在 Docker Volume，不在 Git 仓库中。升级前必须同时备份 PostgreSQL、MinIO 和独立托管的
`FLOWTEST_DATA_ENCRYPTION_KEY`：

```bash
./deploy/compact/backup.sh /srv/flowtest-backups/2026-08-19
```

备份目录必须是不存在的绝对路径。不要把 `.env` 或业务备份提交到 GitHub。

带真实数据的公司环境不得只执行 `git pull` 后直接重建。应由发布工作站从干净、审批过的 Git Commit
生成新离线包，再按 [`compact-offline-upgrade.md`](compact-offline-upgrade.md) 执行事务式升级；只有
退出码为 0 且证据 `status=passed` 才能切换活动目录。`status=rolled_back` 表示旧版本恢复成功，
不表示升级成功。

## 完全离线交付

联网且已安装 Git、Docker 的受信发布工作站，在干净的审批 Commit 上执行：

```bash
git status --short
./deploy/compact/export_offline_bundle.sh \
  /srv/flowtest-release/flowtest-compact-4.0.0-arm64.tar.gz 4.0.0
```

根据目标机 Docker 架构分别生成 `arm64` 或 `amd64` 包。将压缩包和 `.sha256` 通过不同的公司受信
渠道交付到目标机；目标机校验摘要、解压后运行：

```bash
openssl dgst -sha256 flowtest-compact-*.tar.gz
cat flowtest-compact-*.tar.gz.sha256
tar -xzf flowtest-compact-*.tar.gz
cd flowtest-compact-*/
./deploy/compact/install_offline.sh
```

安装器会再次验证逐文件哈希、5 个镜像 ID 和目标架构，并以 `--pull never --no-build` 启动。
正式包拒绝未提交源码生成的 `SOURCE_STATE=dirty` 制品；不得用开发演练开关绕过该限制进入公司环境。

## 验收清单

- `verify.sh` 通过，且恰好 6 个服务处于运行状态。
- <http://localhost:3000> 可登录，`/api/v1/ready` 返回正常。
- 已修改初始管理员密码，`.env` 仅部署管理员可读并已独立托管。
- 未向 Git 提交 `.env`、`images.env`、离线镜像包、诊断目录或业务备份。
- 需要跨主机访问时已启用公司 TLS、受控内网地址和 Secure Cookie。
- 首次录入业务数据前已验证备份目录、恢复责任人与升级维护窗口。
