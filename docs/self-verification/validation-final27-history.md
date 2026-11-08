> 历史记录：以下仅描述当时状态，不作为当前通过证据或本轮操作指令。当前状态见 [current-validation.md](current-validation.md)。

# v2 持续开发验证记录

2026-10-24 用户已将范围扩充为完成剩余 S5 和全部不依赖模型的验收。新增开发与实际试验见 [S5 续作记录](s5-progress.md)；下面 `final27` 是扩充前封存的来源，不能证明后续源码已经通过。真实模型继续不调用。

本记录补充[首次开发记录](validation.md)，不覆盖历史失败或旧构建收据。逐项实现、适用形态和实际验收分别见[94 项验收账本](acceptance-matrix.md)。基线为 `70e4b513e734c2c47053ecc314db0bbd092f16db`，当前修改尚未提交；HEAD 本身不能代表工作区或镜像内容。

## 当前实现范围

### final27 固定来源的本地验收

本轮最终 H 来源已固定；下面是本地 bootstrap review，审核为 `ci_fixture`、模型调用为 0，不发布远程 Required Gate。94 项目录与 341 个变体保持不变，账本只为完整对应冻结场景的变体填入相应 profile 结果。

| 形态                          | 整体入口                                   | 处置                             | 公开证据                                                                                                                |
| ----------------------------- | ------------------------------------------ | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Standalone `final27-attempt1` | 0；基线 8 批、协议 34、治理 42、扩展 10 包 | 全部专用容器、网络和卷已确认移除 | [完整收据](../../output/selftest-validation-20261024-resume/public/standalone-final27-attempt1/acceptance-summary.json) |
| Full `final27-attempt1`       | 0；另含运行故障 15 变体                    | 全部专用容器、网络和卷已确认移除 | [完整收据](../../output/selftest-validation-20261024-resume/public/full-final27-attempt1/acceptance-summary.json)       |
| Compact `final27-attempt1`    | 0；另含运行故障 15 变体                    | 全部专用容器、网络和卷已确认移除 | [完整收据](../../output/selftest-validation-20261024-resume/public/compact-final27-attempt1/acceptance-summary.json)    |

应用来源固定为 `53aca9c9f4a913ea6de9b8c3d9794b7c4aec91c3b50d020f71b25ea2322120c9`。H 摘要：Standalone `11d5b668b7382bd202425e383690bf17ec454cd98d581ff15450fed8348faf29`，Full/Compact `ef367bfabd411de459c29a4519573ab7fbdbb422339629e7d2935ee115e11224`；差异来自既定的 profile 源码范围，逐文件 SHA 与 H/CLI 源码在[固定来源快照](../../output/selftest-validation-20261024-resume/sources-final27/source-receipt.json)。不同形态的候选/Mock 镜像 digest 分别写在各自收据，不能互相替代。

每个扩展入口含十个包、71 个冻结场景，覆盖错误目标成对验证、真实传输故障、设计质量、治理恢复与 Preview、语义反证、契约增量与槽位、原生控制流、安全边界、初始化恢复和真实令牌过期。它们不是 71 个全部业务成功的 Case：原始失败、预期拒绝、Preview 及未产生正式执行的边界场景按用途分别保留。

各次命令、来源与范围见账本的逐 profile 记录；已用目录不可原样重放，复现须使用新目录。下方历史尝试与早期来源保留，不用于冒充 `final27` 的通过。

### 当前账本与完成边界

- 94 个父项：91 项实现完成，2 项部分实现，1 项待实现。剩余实现变体为 S5 的合成文件上传/下载/清理、并行 Cookie 隔离，以及双 worker claim、重复消息、worker 崩溃和恢复；不将现有调度器局部测试当作完整交付。
- 341 个独立变体：172 项具备全部适用 profile 的本轮通过证据，26 项验收未完整，143 项未执行；49 个父项的全部变体具备当前通过证据。实现完成不等于验收完成。
- 真实 Host/LLM、实际人工审核、远程最新提交 Required Gate、合并后 CI、Windows 原生打包及完整发布验收保持未执行。S5 扩展不在本轮 S0–S4 核心交付范围。其余未执行的产品、UI 与抗误绿变体验收逐项保留在账本，不能从 CLI 三形态通过推导为已通过。
- 当前 MCP 服务仅启用 stateless；未验收实际 stateful 服务模式。目录分页客户端的 4 项行为测试通过，当前部署返回单页目录，不声称实际服务返回过多页。
- 31 套本任务专用项目均已核对容器、网络及卷无残留；日常容器前后均为相同的 10 个。公开证据 676 个文件检查无凭据形态内容或私有输入目录。审计摘要见[资源与公开证据核对](../../output/selftest-validation-20261024-resume/public/final27-audits/acceptance-status.json)。

### 本轮检查与历史检查的关系

2026-10-24 恢复开发后的检查如下。下方保留各次检查的真实范围，不能将不同构建或 H 来源拼成一次完整门禁。

- 后端完整测试：**3125 passed、15 skipped，覆盖率 91.64%，777.12 秒**；日志 `/tmp/flowtest-resume-backend-full.log`。该次采集之后新增的 CLI/O 测试另记定向结果，不计入 3125。
- SQLite 同提案并发审核修复后，61 项相关回归通过；修复前公开 HTTP 竞争确实产生 200/500，修复后明确为 200/409。高风险审批内容绑定修复同时保留。
- 原生 4.0 与设计质量相关联合回归 64 项通过；设计质量 18 场景使用真实 stdio/HTTP SDK，独立 O 子进程及篡改检查通过。此处是 SDK/ASGI 范围，不能代替部署验收。
- candidate17 应用来源为 `53aca9c9f4a913ea6de9b8c3d9794b7c4aec91c3b50d020f71b25ea2322120c9`，镜像为 `sha256:ff3d16566937c96cba29942e38d839d491bc1638958c87efd0508f2a1bdd134b`。Standalone probe21 的安全 5 场景、初始化恢复 3 场景，在精确清理所属栈后均由独立 O 返回 0。见[公开摘要](../../output/selftest-validation-20261024-resume/public/standalone-probe21/acceptance-summary.json)。
- Standalone review22 的 Preview 与治理恢复 12 场景在真实 stdio、HTTP 两种传输下均匹配；专用栈精确停止后，独立 O 返回 0。该次镜像为 `sha256:01beeb8132546475aa4df105741de74d49bfa21b9ebb801943ba9954abae93b0`，应用来源与 probe21 相同，镜像收据分别保留，见[公开摘要](../../output/selftest-validation-20261024-resume/public/standalone-review22/acceptance-summary.json)。旧失败尝试未改写。
- 分批 CI、镜像复用、独立 O、防篡改、schema 及配置取消边界联合检查 **121 passed**，日志 `/tmp/flowtest-schema-ci-targeted3.log`。该次 H/O 共 184 个源文件的类型检查通过；新增 20 份 JSON Schema 与执行模型一致。最终三形态结果见顶部 `final27` 表，执行顺序见[CI 验收说明](ci-acceptance.md)。
- 最终账本、完整目录分页和 schema 具名回归 **33 passed**，日志 `/tmp/flowtest-final27-ledger-verified.log`。新分页测试只使用真实 SDK 数据模型与合成会话，不计为部署的多页服务验收。
- 用户明确要求本轮暂不调用模型，真实 Host/LLM 保持 NOT_RUN。

### 恢复后的分批验收

- Standalone 扩展批 `final23-attempt4` 已由实际 CI 扩展入口返回 **0**：十个包、71 个冻结场景全部通过，扩展环境与一分钟令牌环境均精确清理，模型调用为 0。镜像仍为 review22 的精确候选与 Mock 镜像，Standalone H 摘要为 `ce8280eb76bad1b94b94f96eaa065bcd669435331206f28b3813c60eecf3910c`。见[独立收据](../../output/selftest-validation-20261024-resume/public/standalone-extended23-final/ci-extended-receipt.json)。此收据只证明扩展批，不能代替基线 CI 或其余部署形态。
- 原生控制流专用 `probe25` 三变体实际执行、停止和最终 O 核验均通过；这是独立于扩展批的另一次构建来源收据，见[身份摘要](../../output/selftest-validation-20261024-resume/public/standalone-native25/control-identity.json)。
- 自测相关联合检查记录为 **1176 passed、1 skipped、1 failed**，日志 `/tmp/flowtest-final-selftest-integration-union.log`。唯一失败是原 CI 上传目录测试仍限定两个公开目录；已更新为四个精确白名单目录，之后 CI 治理、原生/增量 CLI 联合 **167 passed**，日志 `/tmp/flowtest-final-ci-governance-targeted.log`。不把定向重跑拼成全量通过。
- 新分页测试加入后，后端最终格式 812 文件及 Ruff 通过，日志 `/tmp/flowtest-final27-backend-{format,ruff}-final.log`；`mypy app` 482 文件、H/O 类型检查 185 文件通过。H 来源快照的 185 个文件逐一 SHA 核对无变化。H 时间诊断仅区分授权前、未来时间与过期三类错误，未放宽时间条件或增加采集值。第三次尝试的时间失败保留；只读时钟测量处于宿主往返区间内，第四次尝试通过，不据此将旧失败改绿。
- 本轮已修复两个 HTTP SDK 客户端争用固定代理端口、原生 CLI 使用不存在的账户详情路由、Full/Compact 使用错误 H 摘要，以及后续失败覆盖首次失败文件的问题。固定来源与收据保存在[源码快照](../../output/selftest-validation-20261024-resume/sources-final26/source-receipt.json)。
- Full、Compact、Standalone 完整 CI 入口的最终运行见顶部 `final27`；以下较早来源不用于填充当前 profile 通过。

### 已封存本地 CI 入口（补充包形态预期修复前）

以下 Full 与 Compact 曾在改密修复后的较早 H 来源完成全部入口，并分别返回 0。各形态内部的基线、扩展及认证过期批复用本形态固定镜像；不同形态的镜像 ID 分开记录，不因相同应用摘要推定镜像相同。

| 形态       | 当前批次                      | 整体结果                                                                                  | 公开收据                                                                                                             |
| ---------- | ----------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Full       | `full-final26-attempt3`       | 0；基线 8 批、协议 34、治理 42、运行故障 15、扩展 10 包，所有专用栈清理完成               | [验收摘要](../../output/selftest-validation-20261024-resume/public/full-final26-attempt3/acceptance-summary.json)    |
| Compact    | `compact-final26-attempt1`    | 0；与 Full 相同必测集合，所有专用栈清理完成                                               | [验收摘要](../../output/selftest-validation-20261024-resume/public/compact-final26-attempt1/acceptance-summary.json) |
| Standalone | `standalone-final26-attempt1` | 2；补充包错误地要求 Standalone 新账号必须改密，其余 7 批及协议/治理原始结果保留，栈已清理 | [历史部分证据](../../output/selftest-validation-20261024-resume/public/standalone26-attempt1-partial/)               |

Full 候选镜像为 `sha256:634b85c9eda6895d082f3a6a7a938553ffe0dc0a4c6d21a3c5357b3cea5524a0`；Compact 为 `sha256:e9b090596c2c64792c8e2e5024529f343c9bea348bc1df7991e6f8b6169ef7b6`。两者应用摘要均为 `53aca9c9f4a913ea6de9b8c3d9794b7c4aec91c3b50d020f71b25ea2322120c9`，H 摘要均为 `2d85b7d26f99316b2a673bd8fa5f60f03927190f86ec8b332a03a21332089022`。完整逐文件来源见[改密修复后的 H 来源](../../output/selftest-validation-20261024-resume/sources-final26-password/source-receipt.json)。真实模型调用为 0，审核仍为自动化夹具；不是实际人工审核或远程 Required Gate。

- 新的自测与 CI 联合检查：**1290 passed、1 skipped，387.13 秒**，日志 `/tmp/flowtest-final-selftest-ci-integration-union2.log`。其后新增的 Full/Compact 强制改密分支经三形态安全、初始化及 CLI 专项 **9 passed**，日志 `/tmp/flowtest-security-required-password-after2.log`；不把后续专项数量加进 1290。
- 前端重新执行格式、Lint、类型、构建及覆盖率检查：**194 文件、1539 测试通过**，覆盖率 statements/branches/functions/lines 为 **86.8% / 82.7% / 86.74% / 89.42%**。日志 `/tmp/flowtest-resume-final-frontend-{format,lint,coverage,build}.log`。本轮没有修改前端源码；已有真实浏览器交互及截图的后端执行来源仍按原收据保留。
- Full 第二尝试的安全探针遗漏首次改密，原始拒绝为 `PASSWORD_CHANGE_REQUIRED`。现已按既有 204 接口完成改密并重新登录，未降低产品认证要求。该失败保留；基线与已完成的六个扩展包另存为[历史部分证据](../../output/selftest-validation-20261024-resume/public/full26-attempt2-partial/)。
- 该阶段公开证据检查覆盖 346 个文件，无凭据形态内容或私有输入目录；最终归档检查见顶部审计摘要。

补充包现按实际 profile 验证新用户状态，仍为每个专用用户正常设置运行所需密码，Full/Compact 的首次改密要求保留。三形态 15 场景参数化原生链路与安全/恢复专项共 **18 passed**，日志 `/tmp/flowtest-supplemental-profile-password-after.log`；修复前 Standalone 分支明确失败，Full/Compact 分支通过。修复后的 H 摘要及三形态 `final27` 重验均见顶部，不将上表不同 H 来源拼作当前完整门禁。

| 范围       | 实现与行为                                                                                                                  |
| ---------- | --------------------------------------------------------------------------------------------------------------------------- |
| 产品工作台 | 组织切换、项目权限、绑定预检、固定包安装、来源审核发布、确认执行、原生运行钻取、双 JUnit、证据下载和历史保留期投影          |
| 运行与调度 | 原生 Case → Suite → Plan → Run；固定 API/Workflow/环境快照；明确的派发恢复、取消、过期 watchdog；保留全部真实 attempt       |
| 证据权限   | 当前任务签名、租约、nonce、精确 Plan Run/执行/子执行范围；O 不携带 A 的普通查看者、审核者、项目 CI 读取或写入凭据           |
| 独立核验   | 冻结黄金规则、完整分母、来源与发布关系、控制记录分页、Mock journal、共享预算、错误节点/阶段/代码、清理和两种 JUnit 分开判定 |
| 部署       | Standalone、Compact、Full 的实际容器、网络、卷、镜像及配置核验；目标实例深度 1 禁止再次自测；配置更新只重建所属 runner      |
| 宿主适配   | 有界 CLI 子进程、受限 MCP 代理、签名任务与预算、独立审核发布、调用及中断收据、八项质量指标；无授权时不启动模型              |
| MCP 负向   | 固定协议 34 场景与治理 42 场景；真实 SDK 2.2.0、stdio/Streamable HTTP、独立预期及反篡改核验；负向验证不等于普通生成执行闭环 |

具体产品及私密运行配置见[工作台说明](product-workspace.md)、[宿主说明](host-llm-adapter.md)。没有新增外部模型调用授权，也没有生成正式受信 CI 状态。

以上列出本轮已实现的通道与行为，不表示 S5 全部扩展或 94 项完整验收已完成。

## 2026-10-23 较早检查记录

以下是各次运行的真实范围，不能把不同检查的数量相加充当当前完整门禁。

| 检查                             | 结果                                                                                                                                                                                 | 完整日志                                                                                                                                               |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 当前后端全量测试                 | **2906 passed / 14 skipped；覆盖率 91.52%**                                                                                                                                          | `/tmp/flowtest-final-backend-pytest.log`                                                                                                               |
| 当前后端静态检查                 | format 773 文件、Ruff 零错误、mypy 482 源文件通过                                                                                                                                    | `/tmp/flowtest-final-backend-format.log`、`/tmp/flowtest-final-backend-ruff.log`、`/tmp/flowtest-final-backend-mypy.log`                               |
| 当前 H 静态检查                  | format 103 文件、Ruff 零错误、mypy 103 源文件通过                                                                                                                                    | `/tmp/flowtest-final-h-format.log`、`/tmp/flowtest-final-h-ruff.log`、`/tmp/flowtest-final-h-mypy.log`                                                 |
| CI 调度顺序与负向探针            | 42 项联合测试通过；旧顺序先冻结 runner ID、再由探针重建 runner，真实 finalizer 行为回归先失败；调整顺序后通过，未改写冻结预期或清理约束                                              | `/tmp/flowtest-ci-runner-order-before.log`、`/tmp/flowtest-ci-runner-order-final.log`                                                                  |
| 当前 Mock                        | 40 项测试通过                                                                                                                                                                        | `/tmp/flowtest-final-mock-tests-fixed.log`                                                                                                             |
| 当前前端完整检查                 | **194 文件 / 1539 测试通过**；statements 86.81%、branches 82.70%、functions 86.75%、lines 89.42%；format、lint、类型、build 通过。长身份摘要与最近批次溢出修复后，另跑 46 项相关测试 | `/tmp/flowtest-s4-identity-layout-coverage.log`、`/tmp/flowtest-s4-recent-batch-layout-targeted.log`、`/tmp/flowtest-s4-recent-batch-layout-build.log` |
| 后端完整检查，保留期及后续接入前 | format、Ruff、mypy 473 源文件；2470 passed / 14 skipped，覆盖率 91.42%                                                                                                               | `/tmp/flowtest-s4-backend-final-pytest.log`                                                                                                            |
| 前端完整检查，派发恢复实现后     | format、lint、类型、1519 个测试、build；statements 86.74%、branches 82.73%、functions 86.68%、lines 89.37%                                                                           | `/tmp/flowtest-s4-frontend-dispatch-final-full.log`                                                                                                    |
| 前端新增状态文案后               | format、lint、类型、build 通过                                                                                                                                                       | `/tmp/flowtest-s4-frontend-final-label-static.log`                                                                                                     |
| 存储保留期                       | 61 个测试；真实上传、封存、删除物理对象后阻断历史当前通过投影；mypy 474 源文件                                                                                                       | `/tmp/flowtest-selftest-retention-targeted-final.log`                                                                                                  |
| 新状态目录恢复既有安装           | 14 个测试；发布资产指纹漂移、低请求预算、截止时间等反例                                                                                                                              | `/tmp/flowtest-selftest-fixed-recovery-final-file.log`                                                                                                 |
| 目标实例防递归                   | 90 个定向测试，包含有效身份和绑定仍被服务端拒绝、零新增批次                                                                                                                          | `/tmp/flowtest-s4-recursion-depth-targeted.log`                                                                                                        |
| 三形态公开配置一致性             | 67 个定向测试；四类配置缺失或漂移均拒绝                                                                                                                                              | `/tmp/flowtest-s4-probe-config-targeted.log`                                                                                                           |
| 独立产品 MCP 凭据                | 真实公开 API 创建专用账户；普通 CLI 令牌轮换不影响产品账户                                                                                                                           | `/tmp/flowtest-s4-product-credential-isolation-fixed.log`                                                                                              |
| 协议与治理包合入                 | 58 个具名及参数化测试                                                                                                                                                                | `/tmp/flowtest-s4-negative-governance-integrated-fixed.log`                                                                                            |

上表为较早构建的检查记录；恢复开发的最新结果见顶部说明。新增候选和 H/O 来源分别留回执，不能沿用旧结果放行。浏览器已实际验证桌面 1440px 无页面溢出、自测区域适配 390px，长身份仍可复制完整值；历史 MCP 批次的双 JUnit 经真实网页下载并逐字节匹配原文件，原始三项含一个失败，独立核验三项零失败。

## 实际隔离证据

`output/selftest-validation-20261023-s4/public/` 只归档白名单身份摘要、独立报告、双 JUnit 和反证摘要。私钥、环境、令牌、完整 MCP 会话和普通业务响应不进入该目录。

- `full-final8/`、`compact-final8/`：各自 core 8、extended 19、MCP 三场景连续两轮、附加引擎 11、native API 12，以及运行故障 15 变体，均完成对应构建的独立核验。附加引擎和 native API 在精确所属栈销毁后才最终通过。重复轮次不增加独立需求变体数。
- `standalone-product-final9/`：产品链路 core 8 已封存通过；其后 MCP 尝试暴露账户轮换及新状态目录恢复缺陷，保留原失败批次，随后已修复并通过相应回归。该目录不能宣称 MCP 最终通过。
- `standalone-product-final14/`：产品链路 core 8 和 MCP 3 均已封存，独立 O 退出码为 0，证据完整且清理完成；预期失败场景保留原始 `failed`，独立核验为 `matched`。MCP 审核模式为 `ci_fixture`，不表示真实模型或真人审核通过。具体身份和批次见[本轮公开摘要](../../output/selftest-validation-20261023-s4/public/standalone-product-final14/acceptance-summary.json)。
- Full14/Full15：整体仍未通过。实际部署暴露 PostgreSQL `UNION` 中空值被推导为 `text`、与 UUID 列不兼容，以及探针重建 runner 后旧冻结清理 ID 与当前 ID 不匹配两类阻断；保留失败尝试，精确所属栈销毁均已完成。Full15 部分原生批次通过不能把整体标绿，见[Full15 公开摘要](../../output/selftest-validation-20261023-s4/public/full-final15/acceptance-summary.json)。
- `full-probe-candidate15-17/`：PostgreSQL 修复后的 candidate15 已在实际 Full 中执行同一只读查询回归，旧候选失败、新候选通过；随后公开受限采证、协议 34 和治理 42 均完整匹配，精确所属栈销毁后两项 finalizer 为 0。协议采证到销毁 198.5 秒、治理 64.7 秒，均在各自 600 秒内。此处仅为 `governance_negative_only / local_untrusted`；不代表普通生成执行闭环或全部三形态验收。见[公开摘要](../../output/selftest-validation-20261023-s4/public/full-probe-candidate15-17/acceptance-summary.json)。
- `mcp-negative-loopback-strict/`：协议 34 场景，104 次 HTTP admission、28 次工具调用；独立 O 为 0。29 类真实 CLI 篡改副本均非零，原始证据 SHA 保持不变。
- `mcp-governance-loopback/`：治理 42 场景，102 次 HTTP admission、22 次工具调用；独立 O 为 0。34 类真实 CLI 篡改副本均非零，原始证据 SHA 保持不变。

final8 候选镜像为 `sha256:2f2264bb0679287a2b8648a7421869832ef03f9c04e0755c9ead2f5d27be2307`，源码集合收据保存在 `sources-final8/source-receipt.json`。后续修复改变了源码或 H/O 摘要，必须重新 build 并使用新的批次。两类 loopback 负向报告只证明自有本地进程，不能填入 Full/Compact/Standalone 部署验收。

## 尚未取得的验收

真实模型调用、指定 Skill 的完整现场任务集、真实人工审核与 assisted 修订均未运行。此前浏览器专用测试账户的审核属于 `ci_fixture`，不能称真人审核；历史误标收据已保留并在账本中说明，不改写旧文件。

当前提交的远程 Required Gate、合并后 CI、Windows 原生发布包及完整发布验收未执行。`local_untrusted`、本地测试通过、历史候选镜像通过，均不能升级为受信 CI 或发布就绪。94 个父项与全部适用变体仍按账本逐项统计，不能以测试数量或选中子集填满分母。

S5 全部能力扩展仍未完成验收；新增固定包及具名测试仅计入各自已证明的范围。
