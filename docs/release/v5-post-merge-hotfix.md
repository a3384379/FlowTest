# FlowTest V5 Post-Merge Hotfix 收口记录

## 1. 结果与基线

- 任务：H0 — V5 Post-Merge Hotfix。
- 开始时 `main`：`945912c399a3e158a18bc5ad132dd1fb283641d3`。
- V5 功能合并：PR [#40](https://github.com/a3384379/FlowTest/pull/40)，
  merge commit `68fbde4b634589d13f263ed0d5a7827ca79aa3b0`。
- H0 Pull Request：[#42](https://github.com/a3384379/FlowTest/pull/42)。
- H0 最终 PR Head：`a7140b8d67a0ae4ea692de22017dc6e06e9b38ce`。
- 合并方式：普通 Squash Merge；合并时间：`2026-08-27T16:47:25Z`。
- H0 merge commit：`65a427ad0ddcfa6704b7c1138a97faa04b277e53`。
- H0 业务代码基线 SHA：`65a427ad0ddcfa6704b7c1138a97faa04b277e53`。
- Gate App 身份修复：PR [#45](https://github.com/a3384379/FlowTest/pull/45)，最终
  Head `a0d93d3bec7367784d3148e5fabe3ff1e17c7095`，普通 Squash Merge 时间
  `2026-08-27T18:37:17Z`，merge commit
  `1bb8c76881926d9fafcaa46f541a7128c717f9bd`。
- Migration Head：`20260823_0045`。

H0 业务修复及其后续 Gate 治理修复均已合并，且对应 `main` 全链通过。H0 未新增 V6
运行时能力，未启用任何 V6 feature flag，未创建 Tag、Release、Beta 或 RC。本文档是
独立的收口证据变更；S48 必须从本文档合并并通过 `main` Gate 后的最新 SHA 开始。

## 2. Hotfix 范围与实现

### 2.1 Project 创建授权顺序

- 在配额检查和任何持久化写入前执行 Tenant `create_project` 授权。
- Organization member、admin、owner 与 sysadmin 可按权限创建 Project。
- viewer 固定返回 `403`。
- 仅持有 Project 级 `project:write` 的 Service Account 不获得 Organization 级创建权限。
- 拒绝路径不创建 Project、Membership 或 Audit 记录。

### 2.2 URL Import DNS Rebinding 防护

- 每次实际连接后从 HTTPX network stream 读取真实 peer address 并重新执行地址策略。
- 校验覆盖初始请求、每次 redirect、脚本、配置与最终文档获取。
- 保留原始 hostname 作为 Host、TLS SNI 和证书校验目标，不把 URL 替换为解析 IP。
- `trust_env=false`，不继承环境代理；redirect 由应用显式处理。
- IPv4、IPv6、IPv4-mapped IPv6、loopback、link-local、private、metadata 地址及 DNS
  解析后变更均 fail closed。

### 2.3 `USER_COUNT` 配额并发语义

- 仅新增成员消耗 `USER_COUNT`；已有成员角色更新不重复计数。
- 删除后重新加入按新增成员处理。
- PostgreSQL 路径在计算和写入前锁定 Organization 行，避免并发超卖。
- Standalone 保持同一业务语义。
- viewer 固定 `403`，硬配额固定 `429`；失败路径不写成功 Audit。

### 2.4 Standalone 0044 历史数据升级

- 真实 0044 形态的 waiver 表即使缺失 revision、supersedes、约束和索引，也会在启动时
  重建为 0045 当前结构。
- 历史行保留并转换为 revision 1，恢复 supersede 链、唯一约束、检查约束、外键和索引。
- 已验证历史数据查询、新 revision、supersede/head、幂等启动、备份恢复和
  Standalone/Full transfer。

## 3. CI 治理收口

原 PR #42 中发现旧 `pull_request` 工作流会执行 PR-controlled Gate 代码；随后本收口
PR 又发现 Controller 未验证 child check 的 App 身份。两个 P1 均未被直接 Resolve，也
未通过放宽保护合并。治理引导过程如下：

1. 临时 ruleset 直接要求 7 个底层 GitHub Actions checks，`strict=true`、无 bypass。
2. 独立治理 PR [#43](https://github.com/a3384379/FlowTest/pull/43) 以普通 Squash Merge
   进入 `main`，merge SHA `e61b34b5c4fb07c37e5b2f97481473af2fc77a87`。
3. PR #43 合并后的 ruleset 首次恢复为仅要求受信 `Required Gate`；本收口 PR 的四类
   Review 随后发现 `scripts/required_gate.py` 尚未验证 Checks API 的 `app.id`，理论上
   其他具有 `checks:write` 的 App 可伪造同名成功 check。
4. ruleset 再次临时切换为直接要求相同 7 个 child checks，仍为 `strict=true`、无
   bypass；独立修复 PR [#45](https://github.com/a3384379/FlowTest/pull/45) 要求每个 child
   check 的 `app.id == 15368`，并补充“较新同名 spoof app”和“只有 spoof/missing app”
   的 fail-closed 测试。
5. PR #45 通过 7 个直接 child checks 后普通 Squash Merge；其 merge SHA 的 6 套 main
   workflows、7 个 child checks 和可信 Controller 首次运行全部成功。随后 ruleset
   `21653796` 恢复为 `main-required-gate`，仅要求 GitHub Actions App `15368` 签发的
   `Required Gate`，且无 bypass。
6. `pull_request_target` Controller 只 checkout 可信 base/default-branch 代码；PR Head
   只作为文件列表、SHA 和 child-check 元数据读取。
7. Controller 在 PR Head 或 main SHA 上先写 `Required Gate=pending`，验证选中的 child
   check 名称、App ID、workflow path、event 与精确 Head SHA 后才写最终状态。
8. PR 文件列表同时检查 `filename` 与 `previous_filename`，分页并在 GitHub 上限处
   fail closed；普通 PR 不能修改 `.github/workflows/` 或 `scripts/required_gate.py`。
9. 最终写状态前重新读取 PR base/head；过期事件只能失败。

PR #38、#39 已评论说明被后续实现吸收、关闭并删除远端分支；PR #40 的 4 个历史
review threads 均已用 H0 证据回复并解决。PR #42 的 P1 线程在 PR #43 和 H0 的可信
Controller 实际成功后才解决。本收口 PR 的 App 身份 P1 线程保持未解决，直至 PR #45
合并、其 main Gate 全绿、ruleset 恢复且本 PR 在新基线上重新通过可信 Gate 后才解决。

## 4. 四类 Review 结论

| Review | 结论 | 证据摘要 |
|---|---|---|
| Requirement Conformance | 通过 | 四项 H0 缺陷均有生产代码、负向与成功路径测试；未扩展 V6 scope |
| Correctness & Consistency | 通过 | 授权先于配额/写入；新增成员计数；PostgreSQL 串行化；0044 数据完整迁移 |
| Security | 通过 | 实际 peer 地址逐连接校验；可信 Gate 不执行 PR 代码；依赖与 8 类镜像扫描通过 |
| Deployment & Operations | 通过 | Standalone Windows、Compact、Full、upgrade/rollback、backup/restore、transfer 全绿 |

合并前 P0/P1 为 0，所有 review threads 已解决，PR #42 为 `CLEAN` / `MERGEABLE`。

## 5. 本地与聚焦验证

最终 PR Head 的本地结果：

- `uv run ruff format --check .`：通过，443 个文件已格式化。
- `uv run ruff check .`：通过。
- `uv run mypy app`：通过，324 个 source files 无问题。
- `uv run pytest`：`626 passed / 4 skipped`，Coverage `90.16%`。
- PostgreSQL 并发成员配额测试使用真实 PostgreSQL，并隔离 async engine/pool。
- 0044 fixture、0045 启动修复、备份恢复和 transfer 回归通过。
- 依赖安全审计无已知漏洞。
- Frontend：N/A；PR #42 无 frontend 变更，Controller 明确记录 `No-op Success`。

Gate App 身份修复另行完成以下本地验证：

- 17 个 `required_gate` 聚焦测试通过，覆盖 spoof/missing App 的 fail-closed 行为。
- `uv run ruff format --check .`、`uv run ruff check .` 与 `uv run mypy app` 全部通过。
- 完整 Backend：`628 passed / 4 skipped`，Coverage `90.16%`。

## 6. PR #42 精确 Head 门禁

所有成功检查均绑定 Head `a7140b8d67a0ae4ea692de22017dc6e06e9b38ce`。

| Workflow | Run ID | Conclusion |
|---|---:|---|
| Backend CI | [33091940108](https://github.com/a3384379/FlowTest/actions/runs/33091940108) | success |
| Security CI | [33091940316](https://github.com/a3384379/FlowTest/actions/runs/33091940316) | success, attempt 2 |
| Compose Smoke Test | [33091939898](https://github.com/a3384379/FlowTest/actions/runs/33091939898) | success |
| Standalone Windows Bundle | [33091940181](https://github.com/a3384379/FlowTest/actions/runs/33091940181) | success |
| V2 to V3 Upgrade CI | [33091940184](https://github.com/a3384379/FlowTest/actions/runs/33091940184) | success |
| Required Gate Controller | [33091937545](https://github.com/a3384379/FlowTest/actions/runs/33091937545) | success, attempt 2 |
| Frontend CI | N/A | no frontend paths |

Security attempt 1 在构建固定 k6 依赖时收到 `proxy.golang.org` HTTP/2
`INTERNAL_ERROR`，因此可信 Gate 正确失败。保留首次失败记录，仅重跑失败的 Security
run；attempt 2 完成源依赖审计、泄漏规则、全部 release images 和 8 类镜像扫描。
Compose 全绿后重跑可信 Controller，它重新核对精确 Head/base 和全部 child checks 后才
写入成功状态。

## 7. H0 Merge SHA 的 main Push 门禁

所有检查均绑定 merge SHA `65a427ad0ddcfa6704b7c1138a97faa04b277e53`，且一次通过。

| Workflow | Run ID | Conclusion |
|---|---:|---|
| Backend CI | [33095049283](https://github.com/a3384379/FlowTest/actions/runs/33095049283) | success |
| Security CI | [33095049261](https://github.com/a3384379/FlowTest/actions/runs/33095049261) | success |
| Compose Smoke Test | [33095049286](https://github.com/a3384379/FlowTest/actions/runs/33095049286) | success |
| Standalone Windows Bundle | [33095049257](https://github.com/a3384379/FlowTest/actions/runs/33095049257) | success |
| V2 to V3 Upgrade CI | [33095049272](https://github.com/a3384379/FlowTest/actions/runs/33095049272) | success |
| Required Gate Controller | [33095049349](https://github.com/a3384379/FlowTest/actions/runs/33095049349) | success |
| Frontend CI | N/A | no frontend paths |

main Controller 记录 Backend test/integration、Security、Compose compact/full、Windows
bundle、upgrade rehearsal 全部 success，Frontend 为 `No-op Success`；最终状态由
`github-actions[bot]` 写入且目标为对应 Controller run。

## 8. Gate App 身份修复证据

PR #45 的所有直接必需 child checks 均绑定 Head
`a0d93d3bec7367784d3148e5fabe3ff1e17c7095`，并由 GitHub Actions App `15368` 创建。

| Workflow | Run ID | Conclusion |
|---|---:|---|
| Backend CI | [33099895713](https://github.com/a3384379/FlowTest/actions/runs/33099895713) | success |
| Security CI | [33099895769](https://github.com/a3384379/FlowTest/actions/runs/33099895769) | success |
| Compose Smoke Test | [33099895909](https://github.com/a3384379/FlowTest/actions/runs/33099895909) | success, attempt 2 |
| Standalone Windows Bundle | [33099895727](https://github.com/a3384379/FlowTest/actions/runs/33099895727) | success |
| V2 to V3 Upgrade CI | [33099895751](https://github.com/a3384379/FlowTest/actions/runs/33099895751) | success |
| Required Gate Controller | [33099895951](https://github.com/a3384379/FlowTest/actions/runs/33099895951) | expected failure |

PR #45 修改受保护的 `scripts/required_gate.py`，因此旧 Controller 按设计失败且在临时
ruleset 下不是必需检查。Compose 首次 Full smoke 在构建固定 k6 依赖时收到
`proxy.golang.org` HTTP/2 `INTERNAL_ERROR`；仅重跑失败的 smoke job 后通过，首次成功的
compact job 保持不变。普通合并未使用 admin、force 或 bypass。

所有以下检查均绑定 PR #45 merge SHA
`1bb8c76881926d9fafcaa46f541a7128c717f9bd`，首次运行通过；7 个 child checks 的
`app.id` 均为 `15368`，`Required Gate` 由 `github-actions[bot]` 在 Controller 完成后
写入 success。

| Workflow | Run ID | Conclusion |
|---|---:|---|
| Backend CI | [33104391927](https://github.com/a3384379/FlowTest/actions/runs/33104391927) | success |
| Security CI | [33104391954](https://github.com/a3384379/FlowTest/actions/runs/33104391954) | success |
| Compose Smoke Test | [33104391926](https://github.com/a3384379/FlowTest/actions/runs/33104391926) | success |
| Standalone Windows Bundle | [33104391899](https://github.com/a3384379/FlowTest/actions/runs/33104391899) | success |
| V2 to V3 Upgrade CI | [33104391910](https://github.com/a3384379/FlowTest/actions/runs/33104391910) | success |
| Required Gate Controller | [33104391902](https://github.com/a3384379/FlowTest/actions/runs/33104391902) | success |

## 9. Remaining Risks 与 V6 开始条件

- URL import 的实际 peer 校验依赖 HTTPX 暴露的 network stream 元数据；元数据缺失时
  设计为 fail closed，升级 HTTPX 时必须保留 characterization tests。
- Ruleset 的可信状态来源绑定到 GitHub Actions app；当前仓库只有 owner collaborator。
  新增 write collaborator 前应重新审计同仓库 workflow/status 写权限模型。
- Windows 实机长时观察、Standalone/Compact 长时运行、真实升级/迁移/备份恢复、企业
  安全审批和发布授权仍属于 V6 GA/RC 证据，不由 H0 伪装完成。
- Key Rotation 仍是 metadata-only，真实轮换未完成；相关 feature flag 保持关闭。

H0 的业务代码基线为 `65a427ad0ddcfa6704b7c1138a97faa04b277e53`，治理修复后的
当前 main 为 `1bb8c76881926d9fafcaa46f541a7128c717f9bd`。S48 必须从本文档
closure PR 合并且其 main push Gate 成功后的最新 main SHA 开始。
