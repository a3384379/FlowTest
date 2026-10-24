> 历史记录：以下仅描述当时状态，不作为当前通过证据或本轮操作指令。当前状态见 [current-validation.md](current-validation.md)。

# 自测开发交接与历史暂停记录

## 2026-10-24 最终交接

当前有效记录为本节；下方为暂停和分阶段恢复时的历史快照，其中的“尚未修复”“待运行”只描述当时状态。

- 代码在独立工作树 `/Users/sqz/.codex/worktrees/mcp-native-selftest/FlowTest`，分支 `codex/mcp-native-selftest`，基线 `70e4b513e734c2c47053ecc314db0bbd092f16db`；尚未提交、推送、合并或更新原始检出。
- 本轮 S0–S4 核心产品开发、CLI/O 与 CI 集成已完成；`final27-attempt1` 的 Standalone、Full、Compact 完整本地入口分别退出 0。各形态固定应用、H 与镜像身份，基线、扩展和认证过期分批验收；所有测试专用栈已精确清理。
- 后端完整 3125 passed / 15 skipped，覆盖率 91.64%；自测/CI 联合 1290 passed / 1 skipped，后续 profile 分支专项 18 passed，最终账本/分页/schema 专项 33 passed，分别记录检查来源，不相加为一次全量门禁。前端 194 文件、1539 测试及格式、Lint、类型、构建通过。
- 账本保留 94 个父项、341 个变体：91 个父项实现完成、2 个部分实现、1 个待实现；172 个变体具备全部适用 profile 的当前通过证据、26 个未完整、143 个未执行。实现剩余为 S5 文件、并行 Cookie 及 worker 恢复扩展；其余未验收项仍逐项保留。
- 用户要求暂不调用模型；真实 Host/LLM 与实际人工审核保持 NOT_RUN。远程最新提交 Required Gate、合并后 CI、Windows 原生打包及完整发布验收均未执行。当前服务仅启用 stateless；客户端分页测试不等于实际多页服务验收。
- 31 套任务专用项目已确认无容器、网络和卷残留；原有 10 个日常容器名称未变。公开证据检查无私有输入或凭据形态内容，不改变产品诊断采集和脱敏策略。

详细来源、失败历史、日志与证据链接见[本轮验证记录](current-validation.md)、[94 项验收账本](acceptance-matrix.md)及[最终状态摘要](../../output/selftest-validation-20261024-resume/public/final27-audits/acceptance-status.json)。复现必须使用新运行目录；不得重新写入已封存目录、复用旧结果标绿，或把独立工作树当作已合并主干。

## 2026-10-24 恢复记录

用户已要求继续；不启动真实模型验收，先完成其余开发和验收。以下暂停记录是历史状态。

- SQLite 同提案并发审核已最小修复：读取 pending 之前取得事务写锁，第二次审核返回标准 409；相关 61 项回归通过。
- 本轮完整后端：3125 passed、15 skipped、覆盖率 91.64%，日志 `/tmp/flowtest-resume-backend-full.log`。后续新 CLI/O 接入另有定向验证，不能把该次收集之后的新增测试计入 3125。
- 设计质量/材料边界 18 场景的真实两种 SDK 传输、独立 O 子进程和篡改拒绝检查已通过。原生控制流与质量联合回归 64 项通过。
- 新增 `quality_run.py`、`quality_verify.py`、`quality_observer.py`、`quality_checks.py`；凭据场景使用实际 readiness 与 discover_services 公开契约，全包 68 工具调用。尚需真实部署最终验收与 CI 接入。
- 新增 `run_boundaries.py`、`boundary_verify.py`。candidate17 Standalone probe21 已实际执行安全 5 场景和初始化恢复 3 场景，所属目标完全清理后独立 O 都为 0。仅归档白名单摘要和双 JUnit，见 `output/selftest-validation-20261024-resume/public/standalone-probe21/`。
- candidate17 应用来源 `53aca9c9f4a913ea6de9b8c3d9794b7c4aec91c3b50d020f71b25ea2322120c9`，候选镜像 `sha256:ff3d16566937c96cba29942e38d839d491bc1638958c87efd0508f2a1bdd134b`。probe21 已停止，未保留运行容器。
- 继续补齐 ST-MCP-021/022 的高级治理/Preview 驱动、最终 CI 集成、三形态验收和账本。真实 Host/LLM、远端合并门禁和发布验收仍未运行。

暂停日期：2026-10-23。用户因额度不足明确要求暂停。全部三个并行开发任务已中断；暂停检查未发现本任务仍运行的开发、测试进程或 `flowtest-selftest-*` 容器。代码保留在独立工作树，未提交、推送、合并或部署。

## 工作位置

- 工作树：`/Users/sqz/.codex/worktrees/mcp-native-selftest/FlowTest`
- 分支：`codex/mcp-native-selftest`
- 基线：`70e4b513e734c2c47053ecc314db0bbd092f16db`
- 原始 `/Volumes/雷电/project/FlowTest` 的无关修改继续保留，恢复时不要覆盖或清理。

## 已取得的验证与边界

- candidate15 历史完整后端：2907 passed、15 skipped、覆盖率 91.51%；前端：194 文件、1539 测试通过。该历史结果不能证明暂停时新增修改已通过完整检查。
- candidate15 的 Full19、Compact19 实际自测闭环及清理通过；本地 UI 验证截图在 `output/playwright/selftest-v2-final-ui/`。未运行远程最新提交合并门禁，也未完成发布验收。
- candidate16 Standalone20 的错误目标包实际通过；传输故障包 v1.0.1 的 14 场景、契约增量包的 7 场景，在真实独占目标停止后最终验证均退出 0。目标已停止，未放宽原始容器身份或清理检查。
- Standalone20 的语义包完成 5 个真实原生执行，独立核验拒绝 4 种错误资产；因后续探测重新配置 runner，该次语义包只有待处置证据，不得标为最终通过。最终需按正确顺序重跑。
- INIT/SEC/Auth 新驱动正式定向检查：59 passed；14 个 H 模块的类型、格式和 Ruff 检查通过。真实 1 分钟认证过期检查已覆盖；不代表新驱动已全部接入最终 CLI/CI。
- 新修复：高风险提案审核后内容变化现返回 `409 MCP_APPROVAL_CONTENT_CHANGED`，保留 trace ID，拒绝前不物化。相关 60 个定向测试及 `mypy app` 482 模块通过。尚未纳入新的 candidate17 镜像或完整回归。

## 恢复时优先处理

1. **已确认、尚未修复的 SQLite 并发缺陷**：两个实际 HTTP accept 同时读到 pending，结果为 200/500，唯一约束冲突；期望 200/409 `MCP_CHANGE_ITEM_ALREADY_REVIEWED`。公开接口特征测试已保存；不能把它当作通过测试，也不要泛化捕获所有 IntegrityError。优先检查 `backend/tests/test_selftest_mcp_review_concurrency.py`，采用最小事务锁或原子 claim 修复，再运行相关定向检查。
2. 完成 `mcp-quality-boundaries-v1`：主驱动 `quality_run.py`、独立 O `quality_verify.py`、18 场景完整真实 SDK/ASGI 测试及篡改测试仍待完成。已有质量模型、5 种设计场景、精确边界调用、受限预算和准备逻辑。`QualityEvidence` 最新要求 `http_rejected`、`tools_rejected` 和固定预算模式；不要丢失这些字段。独立 O 必须重新计算质量规则，不能相信观测中的 decision。
3. 完成独立高级治理包 ST-021/022；保持现有传输故障 14 场景黄金契约不变。完成原生控制流 4.0 包的 CLI、独立核验及回归；其真实 SDK/ASGI/原生链路已有首轮通过，最终状态需重新检查。
4. 将新增故障、增量、错误目标、语义、质量、初始化、安全、过期认证和控制流驱动接入 CLI/CI。所有会重新配置 runner 的探测先运行，再运行依赖原始身份和最终处置的包；不得以放宽身份核验消除失败。
5. 产品修复稳定后构建 candidate17，冻结应用与 H 来源；运行新增代码的完整后端检查、必要集成检查，以及按序 Full/Compact/Standalone 实际闭环。独立认证过期目标使用显式 TTL=1；普通目标默认 TTL=15 不变。不要同时预热多个栈耗尽 Docker 地址池。
6. 更新验收矩阵、schema、当前验证说明和公开脱敏归档。94 项父验收与 341 个变体必须按真实证据逐项标记；不得把局部测试通过写成全部完成。

## 关键日志及私有证据

- 高风险审核修复前：`/tmp/flowtest-mcp-review-approval-before-fix.log`
- 高风险审核修复后：`/tmp/flowtest-mcp-review-approval-after-fix.log`
- 高风险审核类型检查：`/tmp/flowtest-mcp-review-approval-mypy.log`
- 未修复并发缺陷：`/tmp/flowtest-mcp-review-concurrency-characterization2.log`
- INIT/SEC/Auth 联合：`/tmp/flowtest-init-sec-auth-final-union.log`
- Standalone20 故障最终核验：`/tmp/flowtest-fault-standalone20-finalize.log`
- Standalone20 增量最终核验：`/tmp/flowtest-contract-delta-standalone20-finalize.log`
- 历史完整后端：`/tmp/flowtest-final15-backend-pytest.log`
- 故障证据：`/private/tmp/flowtest-selftest-fault-standalone20-contract101-attempt4/public`
- 增量证据：`/private/tmp/flowtest-selftest-contract-delta-standalone20`
- 语义待处置证据：`/private/tmp/flowtest-selftest-semantic-standalone20`

临时目录可能在系统清理后消失。恢复时先核对文件是否仍在，不要将其存在或旧检查结果视为当前事实。INIT 的 `private-worker-state`、私有环境、凭据、SDK 原始内容、原生图和密钥不得加入公开归档。

## 继续有效的约束

- 用户尚未批准真实 Host/LLM 调用及预算，这部分保持 NOT_RUN，不能用 fixture 冒充。
- 未授权提交、上传、PR、合并、部署；恢复开发不自动获得这些授权。
- 保留失败证据，不重复盲目写请求，不清理无关 Docker 资源，不使用个人 Chrome。
- 用户再次要求继续前，不启动新的开发、测试、构建或后台自动任务。

## 2026-10-24 用户已恢复开发

上文为历史暂停快照。用户已明确恢复，并要求暂不调用模型，先完成其它开发与验收。模型、Host、付费 API 继续 NOT_RUN；本轮仍未获提交、上传、PR、合并或部署授权。

- SQLite 并发审核已修复，真实 HTTP 竞争为 200/409；高风险审批内容绑定保留。当前应用摘要 `53aca9c9f4a913ea6de9b8c3d9794b7c4aec91c3b50d020f71b25ea2322120c9`。完整后端 3125 passed / 15 skipped、覆盖率 91.64%；后续 H/CLI 检查单列。
- 设计质量 18、审核恢复 12、传输故障 14、契约增量 7、语义反证 5、控制流 3 及 INIT/SEC/Auth 已完成 CLI/O。两位 HTTP 客户端共享一个专用代理，各自保持不同身份，关闭顺序经回归覆盖。原生 CLI 使用实际存在的账户列表端点精确匹配，不调用不存在的详情路由。
- `ci_extended.py` 分批执行，新增 `configured_probes.py` 先安装全部授权，再冻结最终容器身份。保留 600 秒与 500 请求/100 工具调用上限，短令牌目标单独设置一分钟。新增 20 份 schema 已与模型核对。
- Standalone `final23-attempt4` 扩展验收返回 0：10 包、71 场景，两个专用栈均已清理，模型调用 0。完整公开收据在 `output/selftest-validation-20261024-resume/public/standalone-extended23-final/`；独立原生 probe25 另有三个实际匹配变体。旧失败不改写。
- Full 当前批次为 `/private/tmp/flowtest-ci-20261024-full-final26-attempt2`，日志 `/tmp/flowtest-ci-full-final26-attempt2.log`。第一尝试在构建器解析镜像 ID 时失败，未进入业务测试且已清理；第二次使用已核对的本地标签。Full 本次候选镜像 `sha256:0b95f28e836c1a62794ad57bd71d17590c33d077c01446c3c1df3edd486c3e50`，Mock `sha256:16de77434adc1a50e06e28b112bea3245f5816e7dbef005c730bca39079c00cb`。它们与旧 Standalone 镜像分别记收据，不能因相同应用摘要推定镜像相同。
- H/O 当前 185 文件类型检查通过，后端格式 811 文件、Ruff、mypy 482 文件通过。旧自测联合检查唯一失败为旧上传目录断言，更新四个精确白名单后相关 167 项通过；新的全组检查日志为 `/tmp/flowtest-final-selftest-ci-integration-union2.log`，待实际结果后更新。
- 完整 CI 入口的 Full/Compact/Standalone、账本 profile 填充、公开证据与来源核对仍须完成。当前源码快照在 `output/selftest-validation-20261024-resume/sources-final26/`。若再次暂停，先按 nonce 清理正在运行的专用栈并更新本段；不清理日常容器或个人浏览器。
