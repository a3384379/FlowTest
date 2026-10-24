# 自测 v2 与 S5 当前验证

2026-10-24。S5 合成文件、B 自身文件、并行 Cookie、worker claim/心跳/失效 fencing 和映射漂移预检已实现。按用户要求，真实 Host/LLM 调用为 0。默认宿主入口另实测返回 `NOT_RUN / HOST_AUTHORIZATION_PENDING`，退出码 2、实际模型调用 0；这是正确阻断，未计作模型验收通过。

## 当前来源与完整本地入口

应用摘要 `568155ed56d189884b121e71e0c07ea2c61e085531fdf7cc8c2a620333b92671`。H/O 摘要：Standalone `bfb71f14d8613b164956bdeaaf5c97b2b7f5578023c24902f49a4b1c5b6a06be`，Full/Compact `d343fb7fcf265b9ff07645caf90d3f7f41e566c5adfe4f578100fa8e2222b8e5`。本地基线提交为 `fb4351d7cdcbfa175f8549f135ec9bab75af027e`，该提交已包含约束名和项目准入锁顺序及强度修正；构建时仅产品文档未提交；以实际应用/H/镜像摘要为准，不能拿该 SHA 代替构建内容。完整逐文件快照位于本地 `output/selftest-validation-20261024-s5/frozen45/sources/source-receipt.json`。

| 形态 | 完整进程退出码 | 基线批数 | 扩展包数 | 处置 |
| --- | --- | --- | --- | --- |
| full | 0 | 10 | 13 | 已精确清理 |
| compact | 0 | 10 | 13 | 已精确清理 |
| standalone | 0 | 10 | 12 | 已精确清理 |

各形态包含运行故障 15、协议 34、治理 42、独立 O 抗误绿 28、产品边界 27、纯编译/Quick/FlowSpec 草稿 38。Full/Compact 另有 4 个真实 Celery 故障；Standalone 以 4 个真实阻塞工作流验证本地排队槽，不冒充 Celery 验收。每包最多 500 请求、600 秒、100 工具调用、递归深度 1。对应完整命令、构建身份和报告在本地 `frozen45/public/<profile>/acceptance-summary.json`，公开归档仅精确白名单目录。

原始失败与独立 matched 分开：MCP 核心每轮 3 场景含 1 个原始失败；产品边界两个原生 core 批次共 16 个执行含 4 个原始失败，不改成引擎 passed。`full_pack` 仅指该冻结包，`selected_suites` 和反证 `diagnostic_subset` 均保留各自范围，不能合成全系统绿色结论。

## 全量与专项检查

- 当前后端全量：3386 passed、20 skipped，覆盖率 91.64%，1102.11 秒，日志 `/tmp/flowtest-s5-backend-pytest-all45.log`。其中 5 个依赖真实 PostgreSQL 的并发测试在默认全量中跳过，已在独立真实 PG 中全部通过。O/产品 126 项、迁移/worker/API 43 项、取消回执 34 项及锁顺序相关 117 项专项分别记录，未与全量相加。
- 前端全量：194 文件、1539 测试；statements 86.81%、branches 82.70%、functions 86.74%、lines 89.42%；格式、lint、类型、构建通过，此后未改前端源码。Mock 42 项通过。
- 最新 backend/H 全部格式与 Ruff 通过，app/平铺脚本 mypy 526 文件、命名空间 H/O mypy 211 文件通过；import-linter 1 个边界保持，CI 路由/信任 167 项通过，Skill evaluation `--check` 通过。37 份具名 JSON Schema 与运行时模型同步；另有三形态实际双 SDK 的 55 个工具输入/输出契约与固定 golden 逐项 SHA 匹配、5 个 Skill 包逐字节同步，见本地 `frozen45/public/schema-catalog-sync.json`。仅按 MCP 规范化四个明确的 annotation 字段别名，不忽略其它差异。
- 新独立 O 反例先复现字段、比较符和来源节点遗漏，再补强固定 API、主流程与图连通性。实际两种 SDK 的编译 38 项匹配；没有发布或执行编译草稿。
- PostgreSQL 0068 down/up 后的 `alembic check` 曾发现两个新约束名为 67/64 字符。已统一缩短尚未发布的 0066 迁移与模型名称，约束 SQL 规则不变。App43 镜像实际 down/up/check 均为 0；当前 App45 的全部模型与迁移文件与该镜像逐字节一致，见本地 `frozen43/public/compact-postgres-migration.json`。旧失败保留。

## 三形态浏览器与补充边界

普通测试账户通过现有 UI 审核并发布 3 个 Workflow、3 个 Case，明确确认后发起真实原生运行，再由单独 O 封存。初始化、生成、执行双击分别只写入 1 次；缺 O、错误项目/批次/场景关系、环境漂移和过期证据均阻断当前通过。实际操作及截图在本地 `output/playwright/selftest-s5-<profile>42/`，每种形态 `ui_exit_code=0` 且专用栈已清理。审核明确为 `ci_fixture`，不计真人或模型。

Standalone/Full 页面证据使用 `3d11`，Compact 使用 `a1bd` 构建，原始收据摘要未替换。之后前端与接口契约没有变化，后端增加项目准入锁顺序修复及两个约束名修正。源码差异和证据适用界限见本地 `frozen45/public/gui-behavior-source-equivalence.json`；新增并发行为由 5 项真实 PostgreSQL 回归和当前三形态完整入口验证，不伪装成另一次全量 UI 运行。Compact 漂移 PATCH 使用独立的新边界窗口，不延长已完成批次的时间或预算。

390px 下自测工作区右边界 378px；既有全局页头仍使文档横向溢出，未计为全应用移动端通过。日常 Chrome、容器及数据保持隔离，只回收任务 nonce 所属资源。

取消后伪造成功回执另有三形态真实 HTTP 补充：有效 O 身份收到 `409 SELFTEST_BATCH_FINISHED` 和 trace ID，前后只读状态相同、零原生执行，销毁后独立 O 为 0。其单变体 recipe、独立 operator SHA 和报告在本地 `frozen43/public/cancelled-revival/`；不冒充完整 CI 包。

## 账本与外部边界

保留完整 94 个父项与 341 个变体，94 项实现完成；当前全部适用 profile 通过的变体 294 个，未完整 8 个，未运行 39 个；全部变体关闭的父项 79 个。详细原因见[账本](acceptance-matrix.md)及机器记录。真实模型的 31 个变体按用户要求保持 NOT_RUN；stateful 变体不适用当前 stateless 服务，保留分母；CI 受信发布相关项不能用本地证据填满。

本文件和 Git 中账本是本地冻结快照。远程运行完成后，以 PR 当前提交检查、远程工件和本地 `output/selftest-validation-20261024-s5/remote/` 补充记录核对实际 PR head 与 tested merge SHA，不回写历史构建收据。远程最新提交的检查、Windows 原生包和工件以 PR 运行实际结果为准，另行核对；本地 `local_untrusted` 不授予正式 Required Gate。治理文件变更仍需维护者受控 Bootstrap，不自动合并、改规则集或自签状态。合并后 CI、真实模型、真人审核及完整发布验收不从这些结果推断。

兼容组合的原始能力与实测范围见本地 `frozen45/public/compatibility-matrix.json`：候选 A→固定 Mock、候选 A→候选 B 已按各形态验证；稳定 A→候选 B 缺少四个新接口，明确 unsupported，没有降级契约。

较早 Compact 有一次地址池耗尽而未进入场景；随后 Compact41 和 Full43 产品批次缺执行 ID，整轮失败且保留证据。Full43 的只读诊断确认 PostgreSQL 死锁：原生执行先取项目准入再取组织配额，自测路由校验先锁环境再等待配额，执行插入的环境外键形成环。真实 PostgreSQL 锁屏障先稳定复现失败，修正为项目准入→环境/端点后 4 项回归通过；环境修改、已有端点修改和新端点外键插入仍正确阻挡。初次修复见本地 `frozen44/public/postgres-lock-regression.json`，但较弱项目锁在原生准入阶段升级仍有锁环。

Compact44 完整入口发现 3 个内部错误；独立限定的 2 对原生批次再次复现 2 个 `DeadlockDetectedError`，涉及最终 `UPDATE workflow_executions`、环境外键和 `Project FOR UPDATE` 升级。新增真实 PG 屏障稳定复现后，改为最初即取得原生相同 `FOR UPDATE`，5 项回归通过且保留环境/端点保护；证据在本地 `frozen45/public/postgres-lock-upgrade-regression.json` 和 `runtime-deadlock-reproduction.json`。新来源最终结果见上表，旧失败不改写为通过。其余历史见[早期 S5 记录](s5-development-history.md)、[扩充前记录](validation-final27-history.md)。实现及部署说明见[S5](s5-progress.md)、[CI](ci-acceptance.md)。

Standalone45 首次启动遇到本地并行创建的子网分配冲突，未进入任何场景且已清理；错开启动、使用新 nonce 的第二次完整入口通过。完整旧尝试保留，不替换失败记录，不清理日常网络。
