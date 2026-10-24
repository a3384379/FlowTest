# 系统自测工作台与外部代理

本文描述 S4 的实际实现与运行方式。需求范围见[实施基线](implementation-baseline.md)，逐项覆盖与未运行状态见[验收矩阵](acceptance-matrix.md)。历史 S1/S2 结果保存在[首轮验证记录](validation.md)，不能替代本轮构建的验收。

## 产品链路

质量中心的“系统自测”页从当前用户、组织和项目读取模板及部署登记的 binding。初始化先调用预检，再以独立确认提交安装；浏览器只能选择服务端登记的隔离目标。外部 H 领取安装任务，通过已有 Workflow、Case、Suite 与 Plan 接口创建并发布固定资产，回传版本和指纹映射。

固定运行先冻结场景集合、必测集合、预算、构建和环境身份；H 配置本批独立 Mock 场景并冻结核验 manifest。服务端通过已有计划运行器创建真实 Run。派发结果不明时保留同一个 Run 的恢复入口，不创建第二次业务执行。O 等待每个原生执行及 attempt 结束，读取只读执行证据、Mock journal 和生命周期资源状态，上传 manifest、evidence、核验报告及两份 JUnit，最后封存批次。

队列派发结果不明时，固定包和 MCP 页面提供“恢复原运行派发”。确认窗展示已冻结的原生 Run ID；恢复仍核对当前执行权限、绑定、批次、资源快照，以及 MCP 的完整来源集合。缺少唯一 Run、批次已封存或普通运行中的批次不开放此入口。

MCP 模式先现场生成，再进入已有提案审核页和发布页。默认 H 只等待人工审核、物化和发布结果；它不能替代用户接受提案。发布定义必须与提案内容、API 固定版本、Oracle 映射一致。满足来源核验后服务端才生成 Suite/Plan 快照，用户再确认运行。报告页可从原生执行钻取所属自测场景及来源。

原始执行 `failed` 与独立核验 `matched` 分别展示。故意写错断言的负向 canary，只有实际运行失败且错误节点、阶段、代码与独立目标证据都符合预期时，独立核验才会匹配。子集结果保留自己的分母；真实宿主未连接或未运行时显示 `NOT_RUN / WAITING_FOR_HOST`。

## 组织与会话边界

全局组织选择器仅展示当前用户已授权且可用的组织，以及个人/默认域。保存的偏好只含用户绑定的组织 ID，刷新后先重新读取授权组织，再挂载项目查询。切换组织会清理旧查询并重建项目视图；未保存的编辑按既有草稿保护规则处理。退出登录和用户切换仍清理组织选择。

自测查询键包含用户、组织、会话 epoch、项目、binding、installation 和 batch。来源与下载响应必须仍属于当前上下文，旧批次迟到的响应不能覆盖当前页面或触发文件下载。

## 部署登记与权限

- `FLOWTEST_SELFTEST_BINDINGS`：部署允许的 A/B/M 身份、实际构建、目标项目、隔离与出站许可；不接受浏览器传入任意 URL。
- `FLOWTEST_SELFTEST_PRINCIPALS`：独立 H/O 的公钥、issuer、subject、audience、项目/binding 范围和能力。O 的 `verify` 身份只能核验，不能兼任安装或生成身份。
- `FLOWTEST_SELFTEST_PROBE_GRANTS`：独立负向探针的部署授权，冻结两个合成项目、独立观察者、nonce、清单、构建和不超过 600 秒的期限。只投影有界资源元数据及 Design 摘要，不授予普通产品 O 项目级读取权限。
- H 使用安装/生成权限及独立审核者通道。产品 O 通过部署签名身份和当前任务的租约、nonce 读取当前批次的安全证据；其运行时文件不携带 A 的项目级只读令牌、普通查看者 JWT、审核/发布或 B 所有者凭据。B 的只读身份用于核对合成业务资源后置状态。
- 登记能力按模式校验。确定性 H 在线不能证明真实模型宿主在线。真实宿主还必须提供模型、宿主、Skill、任务和预算指纹及真实工具调用计数；预算指纹须由部署 principal 显式授权。
- 外部代理使用短期签名 JWT、绑定任务与 nonce 的租约、revision 并发控制及续租。租约过期不能自动抢占重跑未知业务写入。

本地代理和浏览器不能声明 `trusted_ci`。只有部署授权的独立核验身份及冻结的 CI run/attempt 才可能满足相应来源条件；实际正式 Required Gate 仍由现有受信 publisher 发布。

## 本地隔离运行

以下命令从仓库根目录运行。`STACK` 和 `STATE` 应替换为本轮全新、明确拥有的临时目录；不要复用失败批次目录。

```sh
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.local_stack start \
  --directory "$STACK" --runtime-image "$RUNTIME_IMAGE"
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.product_setup \
  --directory "$STACK" --state-directory "$STATE"
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.product_agent \
  --directory "$STACK" --state-directory "$STATE/tasks" \
  --config "$STATE/agent-config.json" --role harness --review-mode human \
  --timeout-seconds 1800
```

O 需在另一个进程使用同一个配置及任务目录，指定 `--role observer`。H/O 的私钥和角色运行时文件只允许当前用户读取；不得纳入 Git 或 CI artifact。`product_setup` 仅为已核实 ownership 的本地临时 A 登记公开配置，并通过公开 API 进行初始化；它不启动模型宿主。

`product_setup` 同时支持已由 `profile_stack` 创建的 Full/Compact 栈。配置变更只重建本轮 runner API，重新冻结身份，并核对其余容器、数据库、队列、对象存储与网络均未变化。产品 H 使用独立机器账户；重新发放普通 CLI 账户的令牌不会撤销该产品任务的权限。

源码、Mock 或核验代码变化后，必须重新构建并重新核实 binding。H/O 核验器摘要变化会拒绝旧配置，不能修改旧回执的指纹冒充新构建。对本轮临时环境重新 setup 时使用新的私有状态目录，并保留原失败记录。
本地部署 binding ID 由 ownership nonce 和实际构建身份共同确定；同一构建重复登记保持相同 ID，新构建生成新 ID，避免覆盖旧安装的冻结身份。原失败安装保留在旧绑定下，未知写入不会因新构建而被重放。

`--review-mode ci_fixture` 仅用于显式拥有的隔离验收，仍经过真实公开审核、物化和发布接口。`--review-mode ui_fixture` 只等待浏览器中的测试审核者操作，记录的证据类型仍为 `ci_fixture`。两者均不能记录为真人审批或真实 LLM 验收；默认 `human` 保留给实际人工审核。

O 必须先领取核验任务，才能读取其精确 Plan Run、真实执行及全部 attempt/子执行。读取检查部署身份、项目、binding、批次、租约和 nonce；其他批次的运行不能因同属一个项目而读取。生命周期只额外投影冻结创建/修改步骤的两个合成名称及身份摘要，不返回完整执行、请求头或登录响应。原有通用 `read:execution` 令牌仍是项目级权限，不能将它解释为天然绑定单次运行。

## 部署形态与 CI

Standalone 使用独立 A/B 数据卷；Compact 和 Full 使用各自独立 PostgreSQL、Redis 与对象存储。Full 为 A/B 分别配置一般与数据 worker，Compact 合并各实例的 worker。M 的业务与 O 的管理监听分离。启动器核对实际镜像、命令、环境、网络精确成员、卷及 ownership nonce，不能只凭 Compose 配置或 profile 标签认定隔离。

`FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH=1` 标识目标实例，禁止该实例预检或启动下一层自测；runner 为 0。启动器核对容器的实际值，页面隐藏操作不能替代这一服务端保护。

```sh
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.profile_stack start \
  --directory "$PROFILE_STACK" --source-stack-directory "$STACK" --profile full
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.profile_stack verify \
  --directory "$PROFILE_STACK"
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.profile_stack stop \
  --directory "$PROFILE_STACK"
```

CI 入口为 [scripts/selftest_ci.py](../../scripts/selftest_ci.py)。普通候选构建与受信 H/O 使用独立 checkout；候选 Python 不进入宿主的导入路径，候选 MCP gateway 在候选容器内执行。三种形态分别运行 core、extended、连续两轮 MCP、11 项引擎附加场景与最后的 native API 场景。每一轮均为必需，缺失整个报告目录也会阻断。受保护的 H/O、冻结包、部署和 CI 改动进入 Bootstrap review；`ci:light` 不能降低该检查下限。

CI 只归档有界身份摘要、独立核验报告、两份 JUnit 和 CI 回执，不归档私钥、环境、原始 MCP 会话或凭据。引擎附加包的 Dataset 文件及 native API 的整个临时项目清理，必须在真实停止并核对本批所有容器、卷和网络已消失后，才分别执行最终独立核验。清理前的 observation 和失败 attempt 保留，不能用再次运行覆盖。

新批次将 Mock 的 500 次处理预算、nonce 和绝对截止时间写入冻结 manifest。同一批所有 namespace 和清理共用原子计数，删除或重新登记场景不能重置预算、延长期限。O 独立核对全部 namespace 的实际计数、在途请求结束记录和预算回执；并发场景还核对目标端记录的峰值。该原子计数覆盖 Mock；FlowTest B 的请求另由冻结的流程预算及已有运行器约束。

Full/Compact 还运行 `scripts.selftest.run_runtime_faults` 的 15 变体独立包，验证同计划手动/CI 运行、幂等、并发、响应丢失、排队/运行中取消、cleanup 策略、观察器故障及依赖漂移。它只暂停并恢复本轮精确拥有的 worker；Standalone 没有对应独立 worker，不冒称该故障注入方式适用。每个变体在开始前占据固定分母，报告及双 JUnit 单独归档；Full/Compact 缺少此报告即阻断 CI。

## 保留期与失败处理

数据库只保存安装、批次、场景和来源关联等轻量信息；大型证据走已有 artifact 存储。证据到期或被删除后，历史 verdict 保留，当前投影显示证据过期并阻断通过。原生执行的外键因保留期清理被置空时，也不能继续显示完整 attempts 或可追溯执行。

封存报告读取通过本地文件元数据或对象存储 HEAD 核对存在性，不下载整个证据。单次页面请求共用 5 秒、100 次探测预算；存储不可用或预算耗尽显示证据不可用，不能把未知状态当作仍然完整。

默认不扩大日志、响应或凭据采集。只有授权的合成诊断范围进入证据；既有请求级 redaction 策略仍决定是否处理这些值。超时、断管、租约丢失或未知写入结果保留明确原因和原始 attempt，停止自动重放写入。清理仅作用于已核实属于本轮 ownership 的资源。

截止时间经过后，批次继续显示阻断，授权用户仍可请求取消其原生运行。H 的独立 watchdog 仅对过期、未封存且身份完全匹配的批次恢复取消原来的 Run；未知取消响应最多尝试三次，不能另建 Run。回执只表示取消已请求，原始终态、必要清理和独立封存仍分别核实；已封存结果不能被取消请求改写。

本地定向测试、完整 `make check`、当前候选镜像的隔离运行、远程当前提交门禁和发布验收分别登记。任何一层通过都不替代其余层；真实模型未运行时仍保留完整 MCP 发布验收未完成的边界。

## 参考图与辅助修订

本轮按用户补充的五张图调整系统自测总览、三步初始化抽屉、MCP 生成进度与待审核资产、执行报告来源链和独立核验布局。卡片、进度、场景、版本和证据来自现有授权 API。所选子集、原始失败、未运行、等待证据与 `ci_fixture` 均分别展示，不复制示意图中的示例数值。

人工编辑后使用新的冻结修订批次，真实审核并发布新版本；来源保留首次模型记录与 before/after 差异，明确“不计首次生成”。接口、授权和保留期约束见[辅助修订说明](assisted-revisions.md)。

产品 H 的取消恢复可使用独立的 B 项目编辑者账号；它是普通用户、仅加入目标项目、没有系统或组织管理员角色，也不会传给模型或 O。正式 Run 之前先核对生命周期随机命名空间不存在；原生 Run 和子执行确认终止后，再校验 ID、项目、原创建者、名称与创建时间，回收对应临时环境并读回确认。未知删除不重放，恢复共享三次尝试和累计 100 次管理请求上限。H 清理回执不替代 O 核验，也不改写产品已经封存的结论。
