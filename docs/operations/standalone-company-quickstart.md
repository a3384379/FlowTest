# Windows 云桌面 Standalone 快速安装

项目 GitHub：<https://github.com/a3384379/FlowTest>。

公司云桌面如果不具备 WSL2、SLAT 或 Docker Desktop 条件，请使用 Standalone 离线包。该包不需要
安装 Docker、Docker Compose、PostgreSQL、Redis、MinIO、Node.js 或 uv；开发机预先把 Python 运行时、
依赖 wheels 和前端静态文件打包进去即可。

完整边界、构包和备份说明见
[`deploy/standalone/README.md`](../../deploy/standalone/README.md)。

正式公司试点和迁移请同时使用
[`standalone-pilot.md`](standalone-pilot.md) 记录 SHA-256、72 小时观察和责任人签署。

## IT 需要确认的事项

- Windows 10 x64，允许执行签名/审批后的 PowerShell 脚本；不需要升级到支持 Docker 的硬件。
- 应用目录具有普通用户读写权限，磁盘至少预留 10 GB；默认只使用 `127.0.0.1:8000`。
- 若需同一公司网段访问，由 IT 明确分配监听 IP、Windows 防火墙规则和访问人员；不要开放公网。
- 安全软件允许本目录的 Python 进程创建 SQLite 文件和附件文件。

## 云桌面操作

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd C:\flowtest-standalone
.\deploy\standalone\preflight.ps1
.\deploy\standalone\start.ps1
.\deploy\standalone\verify.ps1
```

`preflight.ps1` 会检查 Windows x64、内置 Python 3.13、离线依赖、前端文件、目录写入权限、磁盘空间和
端口占用；失败时先按 JSON 输出的 `errors` 修复。它不会打印 `.env` 中的密钥，也不需要 Docker、WSL2
或联网。

浏览器打开 `http://127.0.0.1:8000`，使用账号 `admin`、密码 `admin` 登录。Standalone 不强制首次改密；
新建用户和主动修改密码的最低长度为 8 位。`admin/admin` 只适用于默认本机回环试用，若按公司要求开放
内网访问，应在验证完成后立即修改管理员密码。安装人员不要把 `.env` 上传 GitHub、工单或聊天工具。

从 GitHub Actions 下载离线包后，可在 PowerShell 用以下命令校验压缩包；输出必须为 `True`：

```powershell
$expected = (Get-Content .\flowtest-standalone-windows-amd64.zip.sha256 -Raw).Trim().Split()[0].ToLowerInvariant()
$actual = (Get-FileHash .\flowtest-standalone-windows-amd64.zip -Algorithm SHA256).Hash.ToLowerInvariant()
$expected -eq $actual
```

## 运行档位确认

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/runtime-profile
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

预期 `profile=standalone`、`worker_topology=in_process`，Readiness 只有 `database` 和 `storage`
等本地检查，不应出现 `redis`。API URL/Swagger UI 导入、Postman 风格参数与请求体编辑、流程编排、数据节点、
运行观测和历史快照属于公司云桌面轻量包的默认能力；Performance Lab、Environment Lab 和 Runner Fabric
仍不属于该安装范围。

若 IT 要做维护窗口稳定性观察，先保持服务运行，再执行只读探针：

```powershell
.\deploy\standalone\soak.ps1 `
  -DurationSeconds 259200 `
  -IntervalSeconds 30 `
  -OutputPath C:\flowtest-evidence\standalone-soak.json
```

探针证据只包含健康状态、延迟和进程元数据，不包含业务响应、Cookie、Token 或 Secret；退出码非零时
应保留 JSON、`logs\standalone.err.log` 和对应维护窗口记录供 IT 复核。
