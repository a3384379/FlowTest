# FlowTest V6 启动就绪性只读审计

## 1. 审计范围与事实源

- 审计时间：`2026-08-27T20:48:12+08:00`。
- 仓库：`a3384379/FlowTest`。
- 计划文档基线：`main@945912c399a3e158a18bc5ad132dd1fb283641d3`，Migration Head
  `20260823_0045`。
- 本次 GitHub 实际基线：`main@945912c399a3e158a18bc5ad132dd1fb283641d3`，Migration Head
  `20260823_0045`。
- 本地启动时基线：`main@c1b688df64f41a283d5261455a0116a8de04c867`，落后
  `origin/main` 两个提交；审计前已只做 fast-forward，同步到实际 main。
- 优先级：GitHub 当前 main、代码、迁移、PR、Review Thread、Ruleset 和 Actions 结果高于方案文档中的
  状态描述。本次计划 SHA 与远端 SHA 相同，但本地工作树存在上述两提交 Drift。

## 2. 版本与迁移

| 项目 | 当前事实 |
| --- | --- |
| Backend package | `flowtest-backend 3.0.0b3.dev29` |
| Backend application | `3.0.0-beta.3-dev.29` |
| Frontend package | `3.0.0-beta.3-dev.29` |
| 产品事实 | V5 功能 PR #40 已合并；V6 H1 已实现真实 Key Rotation，外部发布门槛未完成，不是 GA |
| Alembic Head | `20260823_0045`（单 Head） |
| Standalone baseline | `20260823_0045` |

当前 README 的首段版本状态仍停留在 V3/V4 叙述，与 V5 已合并的 GitHub 事实存在文档 Drift；H0 不改写
历史验收结论，产品版本关系在 S48 固定。

## 3. Pull Request 与分支

| PR | 实时状态 | Head | 结论 |
| --- | --- | --- | --- |
| #38 Compact Runtime | Open Draft / DIRTY | `4ab1ad9` | 已被 V5 主线吸收，待标记 Superseded 并关闭 |
| #39 Standalone Runtime | Open Draft / DIRTY | `0643732` | 已被 V5 主线吸收，待标记 Superseded 并关闭 |
| #40 V5 Functional Completion | Merged | `5c056d2` | Squash merge `68fbde4` |
| #41 V5 Acceptance Record | Merged | `0858cc4` | Squash merge `945912c` |

GitHub 当前仅有三个远端分支：

- `main@945912c`；
- `codex/s32-runtime-profile-foundation@4ab1ad9`；
- `codex/standalone-runtime@0643732`。

旧 PR 吸收证据：#38 Head `4ab1ad9` 和 #39 Head `0643732` 都是 V5 最终 Head
`5c056d2` 的 Git 祖先；PR #40 的 Head Tree 与 merge commit `68fbde4` Tree 相同。因此两条旧分支的
能力已进入当前 main，不应 rebase 或再次合并。

## 4. Repository Governance

- Repository Rulesets：`[]`。
- `main` Branch Protection：未启用（GitHub API 返回 `Branch not protected`）。
- `main.protected`：`false`。
- 仓库允许 squash、merge commit 和 rebase merge；合并后自动删除分支已启用。
- Secret Scanning 与 Push Protection 已启用。
- 当前操作者具有仓库 Admin 权限，可通过 GitHub API 建立治理规则。

现有 Backend、Frontend、Compose 和 Upgrade Workflow 使用路径过滤，不能直接把这些可能不触发的 Check
全部设为 Required。H0 必须先增加始终触发、按路径汇总适用子门禁的 `Required Gate`，再启用 main
Ruleset。

## 5. PR #40 合并后 Review Threads

以下四条线程在审计时均为 `unresolved=true` 的反面状态，即 `isResolved=false`，且
`isOutdated=false`：

| 优先级 | 文件 | Review Thread | 当前代码复核 |
| --- | --- | --- | --- |
| P1 | `backend/app/services/projects.py` | [项目创建权限](https://github.com/a3384379/FlowTest/pull/40#discussion_r3870041299) | 仍存在 |
| P1 | `backend/app/http/imports.py` | [URL 导入 DNS Rebinding](https://github.com/a3384379/FlowTest/pull/40#discussion_r3870041310) | 仍存在 |
| P2 | `backend/app/services/organizations.py` | [组织成员配额](https://github.com/a3384379/FlowTest/pull/40#discussion_r3870041317) | 仍存在 |
| P2 | `backend/app/core/standalone_schema.py` | [Standalone 0044→0045](https://github.com/a3384379/FlowTest/pull/40#discussion_r3870041322) | 仍存在 |

## 6. 四项 H0 缺陷复核

### 6.1 项目创建权限绕过：存在

`ProjectService.create()` 调用 `_tenant_for_create()` 后直接执行 Project 配额检查和写入。
`_tenant_for_create()` 只解析组织成员身份，没有调用 `tenant.allows("create_project")`。组织 Viewer
因此可以创建 Project 并成为 Project Owner；拒绝路径也没有现成回归测试。

### 6.2 URL Import DNS Rebinding：存在

`HttpImportDocumentFetcher._retrieve()` 先调用 `OutboundRequestGuard.enforce()` 解析并验证地址，随后
`httpx.AsyncClient.stream()` 对原 hostname 独立连接。验证结果没有绑定到 TCP 连接，也没有校验实际
Peer Address。每一跳虽然都会重新调用 Guard，但同一跳仍有 DNS 校验/连接 TOCTOU。客户端已经设置
`follow_redirects=false` 和 `trust_env=false`，仍不足以阻止 Rebinding。

### 6.3 Organization USER_COUNT 配额：存在

`OrganizationService.upsert_member()` 的新成员分支直接插入 `OrganizationMember`，没有调用
`OrganizationQuotaService.enforce(USER_COUNT)`。现有配额实现是“读取用量后判断”，也没有 PostgreSQL
事务锁，因此即使只补一次调用仍可能并发越限。

### 6.4 Standalone 0044→0045：存在

Standalone `BASELINE_REVISION` 为 `0045`，但 Revision 推进白名单只到 `0043`；`0044` 不会推进。
`_ensure_change_regression_tables()` 只执行 `CREATE TABLE IF NOT EXISTS`，不会给已有
`semantic_gap_waivers` 增加 `revision` 和 `supersedes_waiver_id`，也不会补 0045 的唯一、检查、索引和
自引用语义。现有测试只覆盖新库/更早增量基线，没有真实 0044 Waiver Fixture。

## 7. CI Workflow 与实时状态

| Workflow | PR 触发 | main push 触发 | 当前 main@945912c |
| --- | --- | --- | --- |
| Backend CI | Backend/指定 scripts 路径过滤 | 同路径过滤 | 未触发（docs-only） |
| Frontend CI | Frontend 路径过滤 | 同路径过滤 | 未触发（docs-only） |
| Security CI | 所有 PR | 所有 main push | Run `33056832920` success |
| Compose Smoke Test | Backend/Frontend/Compose/指定 scripts 路径过滤 | 同路径过滤 | 未触发（docs-only） |
| Standalone Windows Bundle | Backend/Frontend/Standalone/Transfer 路径过滤 | 所有 main push | Run `33056832914` success |
| V2 to V3 Upgrade CI | Backend/Upgrade/Mock/指定 scripts 路径过滤 | 同路径过滤 | 未触发（docs-only） |

V5 merge commit `68fbde4` 的六项 main Push Workflow 全部成功：Backend `33053160539`、Frontend
`33053160475`、Security `33053160524`、Compose `33053160493`、Upgrade `33053160476`、Standalone
`33053160446`。这些结果只证明该精确 SHA，不替代 H0 新 HEAD 的检查。

## 8. 当前 Feature Flags

配置默认全部关闭：Teams、Test Assets、Advanced Workflows、Data Nodes、Contract Testing、Quality
Center、OIDC、AI、Capability SDK、Plugin Registry、Runner Fabric、Multi Protocol、Event Protocols、
Performance Lab、Environment Lab、Contract Hub、Impact Engine、Quality Intelligence。

Compose CI 会仅在验收环境显式开启现有 V3/V5 所需 Flag。H0 不增加 V6 Flag。

## 9. Standalone / Compact / Full

| 档位 | 存储与执行 | 明确边界 |
| --- | --- | --- |
| Full | PostgreSQL/Redis/MinIO；隔离 Worker | 可按配置启用完整执行面、Performance/Environment Lab、Runner Fabric |
| Compact | PostgreSQL/Redis/MinIO；合并 Worker | 单机六服务；Performance/Environment Lab 固定不可用 |
| Standalone | SQLite/本地 Artifact/进程内队列与事件 | 低并发；无 HA/跨进程续跑；Performance/Environment Lab 和 Runner Fabric 不可用 |

三档位必须共享业务状态语义；Standalone→Compact 只能走版本化 Transfer，不能复制数据库文件。

## 10. 未完成 GA Blocker

- 真实 Key Rotation 已由 V6 H1 实现 re-encrypt/verify/activate/rollback/audit，不再是代码阻塞项；
  外部恢复演练与签署仍归入 H2。
- Windows 公司云桌面真实试点与至少 72 小时观察。
- Standalone/Compact 长时运行及真实 Standalone→Compact 迁移。
- 真实 Backup/Restore 与 Upgrade/Rollback 外部环境签署。
- 连续 RC 观察。
- 企业安全审批、生产发布授权和人工签署。

## 11. 启动判定

```text
H0_START = GO
V6_DOCS_AND_CONTRACT_PREPARATION = GO
V6_FEATURE_BRANCH = NO-GO UNTIL H0 MERGED AND MAIN CHECKS PASS
```

本任务采用 `945912c399a3e158a18bc5ad132dd1fb283641d3` 作为 H0 Baseline。只有 H0 四项缺陷、旧 PR、
Review Thread、Required Gate/Ruleset、精确 HEAD CI 与合并后 main CI 全部闭环后，才记录新的正式 V6
Baseline 并开始 S48。
