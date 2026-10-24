# 真实宿主接入与授权边界

仓库已接入部署专用宿主适配器；本轮真实模型调用为 **0**。ST-MCP-029–036 真实验收保持 `NOT_RUN`，不借用确定性 MCP、ASGI、合成 CLI 或浏览器 fixture 的通过结果。用户的模型、外发数据和预算授权尚待确认。

## 已实现的路径

部署审批方签名与部署 allowlist 同时约束任务、模型、宿主版本、Skill、合成数据、review_mode、审核者、期限及一次 attempt。默认 CLI 只生成 `HOST_AUTHORIZATION_PENDING / NOT_RUN`。普通项目 owner 不能自签授权。

可信 H 经 `_protocol` 连接同一候选容器内的官方 MCP SDK。模型经无凭据私有 Unix socket/stdio 代理自行选择生成工具；H 不调用确定性生成器代做生成。项目/环境、上游 Schema、工具数、结果字节、共享 deadline 均有界。预算拒绝、未知结果及未授权错误写独立终止回执并立即结束自有子进程组。

第一阶段真实 MCP Workflow 提案 → 授权主体独立审核/apply/publish → 只读核对固定版本 → 第二阶段模型提出 Case → 再独立审核发布。单接口使用真实 DesignCompilation；五接口环境生命周期使用真实 IntegrationPlan/Compilation，保留五份生成设计、来源及 Oracle。仅做结构性设计组合，不另写执行图。

Attempt 使用私有 O_EXCL 预约及 CAS 状态迁移。同一授权只允许一个 attempt；未知/运行中/终态不能重放。`--resume-known-review` 只恢复仍持有效 lease 的已知待审边界，不重新运行第一阶段。超时、修订任务或授权均须新授权与新 attempt，旧证据保留。

产品 H 通过现有机器 lease、generation、artifact、materialized API 登记真实提案和固定资产。准备 Mock 独立命名空间、冻结 Suite/Plan 来源及独立黄金后，正式执行仍由现有网页确认执行入口完成。网页没有启动模型/子进程的接口。

O 仅接收 `TaskEvidenceReader` 的 lease-bound A 证据、M 管理凭据和 B viewer。O 从签名任务、冻结包与固定 Suite/Plan 快照重建 manifest，核对 H 的冻结结果，再采原生执行、M journal 和 B 后置。O 没有 A 通用读取/capture/writer 凭据。未完成、全局 Observer 错误、过期或 cleanup 不明均不能变绿。

仅在授权中预先列明的只读工具、结构化 error_code、允许修改字段及后续成功回执全部吻合时，允许记录 read repair；失败回执仍为 success=false。未知或 mutation 失败不能自动重试。独立宿主核验保留全部其他来源、断言、原始结果检查。

## 八项独立质量指标

`host_quality.py` 保存冻结 taskset 版本/摘要、exclusions、全部 attempt、未运行任务和分子/分母：协议可用率、Design 结构合法率、可执行资产生成率、required Oracle 落地率、首次生成执行符合率、assisted 后符合率、固定缺陷检出率、来源完整率。

零分母为 `NOT_EVALUATED`；已开始但缺观测为 `INCOMPLETE`，不删除分母。未运行任务单独列出，coverage 标明 NOT_RUN/PARTIAL/COMPLETE。assisted 必须保留前后提案/摘要、原因与审核者和 review_mode，不覆盖首次结果。实际 O 输出独立 `host-quality.json`；没有模型自评分输入。修改后的资产不能冒充首次原始来源通过。

跨新授权的 attempt 使用部署 H 身份目录派生的固定 taskset 账本，连续编号并保留失败与未知结果。每份独立观测由部署 O 签名，O 在其私有身份目录保存单调 checkpoint；删除已观察的尾段、回放旧前缀或更换 H 状态目录均会阻断。此证明覆盖 O 已观察历史；首次 O 观察之前，H 从未呈交的事件依赖可信 H 部署目录完整性，不能声称已证明这些事件没有被删除。模型 workspace 无权接触 H 账本或 O checkpoint。

已发布来源的人工修订走新的 assisted 批次：冻结 `assisted_before_batch_id`，保持原 Host trail、原授权、失败结果与来源不变；新授权仅绑定本次修订任务。本次模型调用数为 0。实际用户创建并独立审核、发布新的 Workflow 与 Case 后，H 只读核对前后版本、原因、actor、审核模式和逐字段 diff；服务端与 O 保留全部 required Oracle、Design、编译及 API 来源。新批次仍须确认正式执行，after 结果只进入 assisted 指标。Case 用户提案入口为该新批次的 `assisted-case-proposals`，不允许机器冒充用户。before 尚无已发布来源、来源过期或存在未知写结果时明确阻断，不补造 before 图或证据。

## 部署入口与前提

入口为 `python -m scripts.selftest.run_host`。默认无执行。运行须显式 `--run-authorized --host-config <私有文件> --agent-config <既有产品代理配置> --directory <已验证owned栈> --state-directory <私有状态目录> --role harness|observer`。独立入口与产品代理均在读取角色凭据和联网前复核公开 Docker 归属、镜像、源码、网络和端口。

`HostRuntimeConfig` 只来自部署文件：宿主二进制/版本、独立 CODEX_HOME、空的私有 workspace、精确 Skill、冻结 task、审批 JWT/公钥/allowlist、工具隔离证明。不要复制日常认证目录。relay 可设为绝对 Python 路径，`relay_prefix_args` 仅含打包后的 `host_proxy_stdio.py` 绝对路径。模型子进程环境没有 FlowTest/Agent/Observer/JWT 私钥。

H principal 必须由部署配置具有 `host_llm_mcp`，独立 O 具有 `verify`。缺配置时现有服务保持 WAITING_FOR_HOST。宿主配置不能由浏览器输入。`product_agent --host-config` 已分派到同一生成、只读采证和质量报告路径；缺配置不能回退成确定性生成。历史修订还须由部署配置列明归档授权文件，只在其原始有效时段验证归档证据，不能把旧授权用于新的模型调用。

若消费信息不可得，只记 `unknown`，不虚构费用。time/tool/attempt 有界不等同实时 token 或消费硬限制；仅当授权明确要求硬消费限额时，才要求部署提供独立 quota 证明。未知写结果不自动重放。

## 失败后的独立诊断

`scripts.selftest.run_host_diagnosis` 是另一个显式入口，不在生成或原生执行后自动触发。默认 `NOT_RUN`。授权运行须提供 `--run-authorized --host-config <DiagnosisConfig> --agent-config <部署配置> --directory <owned栈> --output-dir <新目录>`，并为新的 `DiagnosisTask` 取得新签名授权。`DiagnosisConfig.runtime` 使用上述私有宿主配置，`task_file` 此时为诊断任务；另指定原 manifest/evidence/verification 三个私有文件及部署 H 身份目录下固定的 `host-diagnosis-attempts`。JSONSchema 位于 `selftest/schemas/host-diagnosis-*.schema.json`。

任务冻结原 batch/scenario/execution、Workflow 固定版本与指纹、错误/节点/阶段、全部 required Oracle 及三份 O 文件 SHA。H 核对原批次仍封存且证据完整，精确比对场景的 O evidence/verification 引用；不接受尚在执行、重复 artifact、其他执行或过期来源。诊断代理只公开 `inspect_run_evidence` 和 `diagnose_failure`，参数精确限制到该失败 execution。生成、修复提案、审核、发布、运行工具均不可调用。

模型须亲自读取这两个现有 MCP 工具并给出有界解释与支持调用序号；H 对照真实分类与 product-defect guard，保留原始产品失败和 Oracle。诊断输出独立 `diagnosis.json`、process/tool 回执、身份/版本/提示/授权摘要，费用仍可为 `unknown`，不计入首次生成指标。预算拒绝、中断、未知或缺证据均阻断，同一 grant 换输出目录也不能重放。真实模型诊断依旧未获授权、未运行；合成 CLI→实际 SDK/ASGI 测试不算模型诊断验收。

## 已验证与待验证

本机仅运行了 `codex --version`、`exec --help`、离线 schema 导出，没有运行 Codex exec/provider。实际 SDK→私有代理→合成 CLI 子进程、公开 ASGI 的提案/审核发布/只读来源链、原生生成器与编译器、独立 O 篡改和八指标分母均有行为测试。assisted 的公开新提案→审核发布→Suite/Plan→原生执行与合成归档→O lineage/quality 分别有测试；旧 seal fixture 不算真实模型首次失败证明。它们不算真实宿主验收。

真实授权后的模型自行选工具、提示注入、固定缺陷检出、实际人工审核/assisted、变更任务/Skill/catalog 后的新版本质量仍须逐项真实验收。自动化审核与浏览器点审只能标 ci_fixture，不能标实际人工。
