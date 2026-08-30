# FlowTest Standalone（Windows 云桌面）

Standalone 是不依赖 Docker、WSL2、PostgreSQL、Redis、MinIO 或虚拟化能力的单进程部署档位。
它适合公司 Windows 10 云桌面进行功能开发验证：API、Web、SQLite、文件附件、工作流和测试计划
都在同一个 Python 进程中运行。Full/Compact Docker 档位仍然保留，Standalone 不写入或转换它们的
数据库和对象存储。

## 公司云桌面边界

- 支持 Windows 10 x64；不检查 BIOS 虚拟化、SLAT、WSL2 或 Docker Desktop。
- 离线包可以包含 Python 3.13 运行时和全部 Python wheels，云桌面只需要允许运行 PowerShell、
  本机回环端口和写入应用目录。
- 建议至少 2 个 vCPU、4 GB 内存、10 GB 可用磁盘。Core2 Duo 级云桌面可以用于低并发功能测试，
  不作为容量或性能测试环境。
- API URL/Swagger UI 导入、Postman 风格请求体与多参数编辑、可视化流程编排、数据节点、运行观测和历史快照
  在 Standalone 包中默认开启；Teams、契约、质量和多协议能力也使用同一进程内实现。
- Performance Lab、Environment Lab 和 Runner Fabric 在该档位固定关闭；AI 和 OIDC 默认关闭。需要访问的
  HTTP、GraphQL、gRPC、Kafka 或外部 Redis 目标仍需公司网络策略单独放行。
- 所有业务数据位于 `data\flowtest.db` 和 `data\artifacts\`；事件历史和限流状态为进程内数据，
  重启后不会保留。业务执行状态、附件和 Snapshot 会持久化。

公司 72 小时试点、责任人签署和 Standalone→Compact 迁移记录模板见
[`docs/operations/standalone-pilot.md`](../../docs/operations/standalone-pilot.md)。

## 在个人电脑生成离线包

个人电脑准备 Python 3.13、`uv`、Node.js 22 和 pnpm 11。先构建 Web，再生成包含 Python 运行时、
Windows wheels、后端源码和启动脚本的目录：

```powershell
cd FlowTest
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
.\deploy\standalone\build_windows_bundle.ps1 -Destination C:\release\flowtest-standalone
```

`-Destination` 必须是不存在的绝对目录，脚本不会覆盖已有目录。生成后把整个目录通过公司批准的
渠道复制到云桌面；不要把个人电脑的 `.env`、`data` 或日志复制进去。

如果公司制品流程已提供带 `runtime\python.exe` 的包，则不需要在云桌面安装 Python、uv、Node.js、
pnpm 或任何数据库/缓存服务。

仓库维护者也可以在 GitHub Actions 手工运行 `Standalone Windows Bundle` workflow，下载
`flowtest-standalone-windows-amd64.zip` 和同名 `.sha256`。下载后先在个人电脑校验 SHA-256，再通过
公司批准渠道传入云桌面；该 CI 制品保留 7 天，不等同于正式 Release。

PowerShell 校验命令如下；输出必须为 `True`：

```powershell
$expected = (Get-Content .\flowtest-standalone-windows-amd64.zip.sha256 -Raw).Trim().Split()[0].ToLowerInvariant()
$actual = (Get-FileHash .\flowtest-standalone-windows-amd64.zip -Algorithm SHA256).Hash.ToLowerInvariant()
$expected -eq $actual
```

## 云桌面首次启动

在解压目录打开 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\standalone\preflight.ps1
.\deploy\standalone\start.ps1
.\deploy\standalone\verify.ps1
```

`preflight.ps1` 会检查 Windows x64、内置 Python 3.13、离线依赖、前端文件、目录写入权限、磁盘空间和
端口占用；失败时先按 JSON 输出的 `errors` 修复。它不会打印 `.env` 中的密钥，也不需要 Docker、WSL2
或联网。首次运行如果尚未创建 `.env`，检查会给出提示，随后由 `start.ps1` 生成随机服务密钥。

首次启动会在包根目录创建 `.env`、`data\`、`logs\` 和 `.flowtest\`。Standalone 本地初始账号固定为
`admin`，初始密码固定为 `admin`，不会强制首次改密；新建用户和主动修改密码的最低长度为 8 位。
该简单凭据只适用于默认的本机回环试用，若使用 `-BindHost` 对公司网段开放，应在验证完成后立即修改
管理员密码。访问 <http://127.0.0.1:8000>。
如果需要受控内网访问，使用明确的监听地址启动，并先由 IT 配置 Windows 防火墙：

```powershell
.\deploy\standalone\start.ps1 -BindHost 10.20.30.40 -Port 8000
.\deploy\standalone\verify.ps1 -BindHost 10.20.30.40 -Port 8000
```

默认只监听回环地址，不应直接暴露到公网。日志位于 `logs\standalone.out.log` 和
`logs\standalone.err.log`；停止服务使用：

```powershell
.\deploy\standalone\stop.ps1
```

## 项目出站安全策略与本地接口

每个项目都可以在“项目设置 → 安全策略”中单独控制“启用出站安全策略”：

- Standalone 新建项目默认关闭，适合在云桌面导入或调试 `localhost`、`127.0.0.1` 和公司私网服务；关闭并不等于不校验，仍会校验 HTTP/HTTPS、端口、凭据、超时/重定向和域名解析。
- 开启后执行严格模式：回环、链路本地、云元数据和保留地址会被拒绝；私网目标必须匹配“允许私网 CIDR”，域名还必须匹配允许域名列表（如已配置）。
- Compact/Full 以及迁移过来的旧项目默认保持开启，避免升级后扩大出站范围。只有具备项目安全管理权限的成员可以切换。
- 该策略统一作用于接口文档/URL 导入、环境和接口执行、工作流、Webhook 及协议调试；修改后新的服务端出站请求立即生效。

导入接口文档和接口列表都使用固定高度滚动区域；接口列表支持名称、路径、说明搜索、HTTP 方法筛选和服务端分页，避免接口数量较多时页面持续增长。

## 长时稳定性探针

探针不启动或停止服务，只读取 `/live`、`/ready`、`/runtime-profile`，并检查 Standalone PID
是否持续存活。它只输出健康状态、延迟和进程元数据，不记录响应体、Cookie、Token、Secret 或业务载荷。
公司维护窗口可执行 72 小时探针；证据目录应由 IT 按公司保留策略管理：

```powershell
.\deploy\standalone\soak.ps1 `
  -DurationSeconds 259200 `
  -IntervalSeconds 30 `
  -OutputPath C:\flowtest-evidence\standalone-soak.json
```

退出码为 `0` 表示整个窗口没有探针失败；非 `0` 表示需要查看 JSON 中的失败代码和本机日志。
探针不会代替真实业务试点，也不会把短时自动化结果写成 72 小时观察证据。

## 备份与恢复原则

备份前会停止本机进程，目标目录必须是不存在的绝对路径：

```powershell
.\deploy\standalone\backup.ps1 C:\flowtest-backups\2026-08-21
```

备份只包含 SQLite 数据库和附件，不包含 `.env`、管理员密码、加密密钥或日志。恢复时先由 IT
确认备份路径后执行；恢复脚本会先把当前 `data\` 改名保留，再复制备份数据：

```powershell
.\deploy\standalone\restore.ps1 C:\flowtest-backups\2026-08-21
```

备份不包含 `.env`、管理员密码、加密密钥或日志；必须使用原来的
`FLOWTEST_DATA_ENCRYPTION_KEY` 和 `FLOWTEST_DATA_ENCRYPTION_KEYRING`，否则加密 Secret、凭据和执行 Snapshot 无法解密。
轮换时先通过安全渠道更新 `.env` 并重启 Standalone，再在组织治理页执行 Prepare/Apply；回滚窗口结束前
保留新旧密钥。

## 迁移到 Compact

Standalone 不能把 `data\flowtest.db` 直接放入 PostgreSQL。迁移时先在 Standalone 包目录停止服务，
再生成逐表、逐 Artifact 校验的传输包；传输包不包含 `.env`、日志或任何密钥文件：

```powershell
.\deploy\standalone\export-to-compact.ps1 C:\flowtest-transfer\standalone-to-compact
```

传输包是一次性新目录，禁止覆盖旧包。它会排除登录会话、OIDC 事务、通知重试队列、Runner 租约/任务
等临时状态；密码只保留现有密码哈希，加密字段保持密文。传输包属于敏感备份，只能通过公司批准的
安全渠道传输。Compact 的 `FLOWTEST_DATA_ENCRYPTION_KEY` 和 `FLOWTEST_DATA_ENCRYPTION_KEYRING` 必须设置为 Standalone
`.env` 中的同一值，但不要把它们写入传输包或命令行。

在已配置好 Compact `.env`、且允许脚本初始化空数据库的 Compact 目录执行（脚本会先启动
PostgreSQL/Redis/MinIO 并运行 `alembic upgrade head`，不会启动业务 Web/API）：

```bash
FLOWTEST_IMPORT_CONFIRM=IMPORT_STANDALONE \
  ./deploy/compact/import-standalone.sh /srv/flowtest-transfer/standalone-to-compact
```

导入前会先离线校验 manifest、所有表行、外键和 Artifact SHA-256；目标数据库非空或版本不匹配时会
拒绝执行。导入在数据库事务中进行，失败会回滚数据库并清理本次新上传的对象；成功后自动启动 6 个
Compact 服务并执行 Readiness 验收。该工具不会迁移 Standalone 的进程内事件、限流窗口或后台任务队列。

Standalone 当前使用模型元数据创建初始 SQLite Schema，并记录 `20260822_0036` 基线 Alembic revision。后续版本升级
必须使用项目提供的升级说明和备份，不要手工删除 `flowtest.db`。

## 验收与故障定位

`verify.ps1` 检查 `/api/v1/ready`、`/api/v1/runtime-profile` 和 Web 首页，并确认 Readiness 不含
Redis 检查。出现启动失败时先查看 `logs\standalone.err.log`，再确认：

1. 包中存在 `runtime\python.exe` 或云桌面安装了 Python 3.13；
2. `frontend\dist\index.html` 存在；
3. 应用目录和 `data\` 可写；
4. 8000 端口未被其他程序占用；
5. `.env` 中没有被安全软件改写的换行或引号。

Standalone 的本地进程调度不提供多机 HA、崩溃后任务续跑或性能容量保证。需要这些能力时，回到
Compact 或 Full Docker 部署，并按对应手册验收。
