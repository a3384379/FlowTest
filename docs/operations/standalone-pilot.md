# Standalone Windows 云桌面试点与迁移记录

本记录用于 V4 S34/S37 的公司云桌面验收。自动化 CI 只能证明构建和短时链路可用；Windows x64
云桌面上的 72 小时运行、公司网络策略和 Standalone→Compact 真实迁移必须由 IT、运维和业务负责人
在目标环境执行并签署。

## 试点前冻结

| 项目 | 记录 |
|---|---|
| GitHub Commit / PR | `bed1047` / PR #39 |
| Windows 包 SHA-256 | 待填写 |
| Windows 版本/Build | 待填写 |
| 云桌面 CPU/RAM/磁盘 | 待填写 |
| 试点负责人/运维/安全审批人 | 待填写 |
| 监听地址/端口/防火墙规则 | 待填写 |
| 数据目录与备份目录 | 待填写 |

目标电脑只接收已批准的 ZIP 与 `.sha256`；不要传输源码、`.env`、密钥、原始日志或业务数据库。
解压后先执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd C:\flowtest-standalone
.\deploy\standalone\preflight.ps1
```

检查输出必须为 `status=passed`。首次启动由 `start.ps1` 生成 `.env`；使用初始账号 `admin`、密码 `admin`
登录即可，Standalone 不强制首次改密（若开放内网访问，验证后立即修改）。记录
`/api/v1/runtime-profile` 的 `profile=standalone`、
`worker_topology=in_process`，并确认 Readiness 不包含 Redis。

## 72 小时观察

保持同一进程运行，不人工重启、删除 `data\`、修改证据文件或替换 `.env`。执行：

```powershell
.\deploy\standalone\soak.ps1 `
  -DurationSeconds 259200 `
  -IntervalSeconds 30 `
  -OutputPath C:\flowtest-evidence\standalone-soak-bed1047.json
```

每天用同一测试项目执行一次登录、API 调用、Artifact 上传/下载、Workflow 发布/执行和报告查看，
并记录用户数、项目数、Artifact 大小、执行次数、P95、失败数、进程 PID 变化、磁盘增长和人工干预。
不得把业务响应、Cookie、Token、Secret 或原始日志上传到 GitHub；异常时保留探针 JSON 与受限日志，
通过公司批准的工单渠道处理。

退出标准：探针 `status=passed`、失败数为 0、PID 未变化、Readiness/Runtime Profile 全部正常、
业务样例无数据丢失，并由业务负责人、运维和安全审批人签署。

## Standalone→Compact 迁移演练

1. 在 Standalone 维护窗口停止服务并备份；在个人电脑或受信发布工作站执行：

   ```powershell
   .\deploy\standalone\export-to-compact.ps1 C:\flowtest-transfer\standalone-to-compact
   ```

2. 检查输出目录仅包含 `manifest.json`、`database\` 和 `artifacts\`，确认 manifest 声明 `.env`、日志和
   数据加密密钥未包含。使用公司批准的安全渠道传输整个目录。
3. 在全新、已初始化到 `20260822_0032` 的 Compact 目录设置与 Standalone 完全相同的
   `FLOWTEST_DATA_ENCRYPTION_KEY`，然后执行：

   ```bash
   FLOWTEST_IMPORT_CONFIRM=IMPORT_STANDALONE \
     ./deploy/compact/import-standalone.sh \
     /srv/flowtest-transfer/standalone-to-compact
   ```

4. 记录导入 JSON、数据库/Artifact 数量、SHA-256、Readiness、登录、Artifact 下载、Workflow 发布/执行
   和 Snapshot 验收结果。导入目标必须为空；失败会回滚数据库事务并清理本次新上传对象。
5. 确认进程内事件、限流窗口、登录会话、后台任务和 Runner 临时状态没有被迁移；这是预期的安全边界。

| 迁移项 | 结果 |
|---|---|
| Standalone 导出/manifest 校验 | 待填写 |
| Compact Alembic `20260822_0032` | 待填写 |
| Project/Folder/Secret/Workflow 数量 | 待填写 |
| Artifact 数量与 SHA-256 | 待填写 |
| 登录、发布、执行、Snapshot | 待填写 |
| Compact Readiness/六服务 | 待填写 |
| 回滚责任人与备份位置 | 待填写 |

该迁移演练通过后，V4 的 Standalone 代码和供应链门禁才具备公司部署证据；没有真实 Windows 试点和
迁移记录时，不创建 V4 正式标签。
