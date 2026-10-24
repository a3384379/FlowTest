# 原生自测与 MCP 生成闭环

本目录保存冻结任务、独立期望和缺陷变体。实现基于 v2 方案，开发阶段和验收证据分别记录在
[实施基线](../docs/self-verification/implementation-baseline.md)与[编译接口说明](../docs/self-verification/design-compilation.md)。
产品入口、H/O 部署权限与 Full/Compact 运行方式见[系统自测工作台](../docs/self-verification/product-workspace.md)。

`deterministic_mcp` 使用锁定 SDK 的真实 stdio 或 Streamable HTTP 进程，现场生成 Design、提案、Workflow 与 Case。
它不代表真实模型宿主验收。`host_llm_mcp` 缺少登记宿主、Skill、供应商授权或预算时返回
`NOT_RUN / WAITING_FOR_HOST` 和退出码 2，不调用外部模型。

真实宿主的部署配置、私有 MCP 代理、两次独立审核、完整 attempt 账本与八项质量分母见
[宿主接入说明](../docs/self-verification/host-llm-adapter.md)。入口为 `scripts.selftest.run_host`，
默认不执行；产品代理须显式提供部署的 `--host-config`，不能从网页上传可执行路径、认证或预算授权。
模型仅能提出提案，正式执行仍走冻结的 Workflow→Case→Suite→Plan→Run。
人工修订使用新的 assisted 批次保留 before/after 与原始失败，不计为首次生成成功；缺原发布来源或未知写结果会阻断。
失败后的 `scripts.selftest.run_host_diagnosis` 也须独立的新签名任务与显式执行开关，只读该已封存失败的
`inspect_run_evidence` / `diagnose_failure`，不会自动修复、审批或重跑；真实模型诊断仍为 `NOT_RUN`。

## 本地隔离环境

从仓库根目录运行。先准备当前锁定依赖和一个已经存在的本地 FlowTest 后端 runtime 镜像。
启动器以该镜像为运行时底座，重新同步当前锁文件并复制当前源码构建候选镜像；不会选择或修改其它 Compose 栈。

```bash
cd backend
uv sync --frozen --extra dev
cd ..
export FLOWTEST_SELFTEST_RUNTIME_IMAGE=your-local-flowtest-runtime:tag
backend/.venv/bin/python -m scripts.selftest.local_stack start \
  --directory /private/tmp/flowtest-selftest-example \
  --runtime-image "$FLOWTEST_SELFTEST_RUNTIME_IMAGE"
```

启动器创建独立 A、B、Mock 业务面和 Observer 管理面。A/B 数据卷、签名与加密密钥不同；管理面不接执行网络。
对外仅发布随机的 `127.0.0.1` 端口。引擎仍使用项目出站策略，仅允许安装 binding 的具体内部主机及子网。
每次特权请求前重新验证 Docker 归属、nonce、镜像、源码和锁文件摘要，禁止替换为任意 URL。

私密配置仅存放在权限为 `0600` 的 `private.env`，不得上传或复制进证据。
安装 journal 只保留资源 ID、阶段和请求摘要；未知结果停止等待检查，不按名称猜测后重复创建。
重复初始化会读取已登记 ID，重新发放内存中的有限权限凭据，不重复创建基础资产。

若启动在创建容器前失败，可恢复同一 ownership 目录；旧 build/start 日志保留，新尝试写入独立日志。
已有部分容器但尚未形成完整 binding 时会阻断，不自动删除现场。

```bash
backend/.venv/bin/python -m scripts.selftest.local_stack resume \
  --directory /private/tmp/flowtest-selftest-example
```

## 生成、执行与核验

```bash
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.run \
  --directory /private/tmp/flowtest-selftest-example \
  --output-dir /private/tmp/flowtest-selftest-results \
  --rounds 2 --transport stdio --suite mcp-core
```

可用 `--transport streamable-http` 启动独立、只监听回环地址的 HTTP MCP 进程，Bearer 随请求传递。
MCP 账户没有审核、发布或正式运行特权；临时 reviewer 仅通过既有公共审核和发布接口接受本批已校验的内容。
Fixture 审核记录为 `review_mode=ci_fixture`，不能充当真实人工审核。

普通计划默认重试 0。每轮冻结精确 expected 集合和非空 required 子集；选入的可选场景也必须完整。
当前执行命令的 `verification_scope` 以实际 manifest 为准，诊断子集通过不能当作完整 pack 或 94 项验收通过。
`mcp-core` 选择生命周期与正反断言三项任务；`mcp-canaries` 只选择两个断言场景，属于诊断子集。
固定基准使用另一批次和输出目录，保留原生控制流及资产包安装路径：

```bash
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.run \
  --directory /private/tmp/flowtest-selftest-example \
  --output-dir /private/tmp/flowtest-fixed-results \
  --rounds 1 --suite fixed-core
```

固定基准包含变量假值、中文、Header、业务断言负例、超时、if、foreach、repeat、retry 和 poll；
具体期望见[固定基准说明](../docs/self-verification/fixed-baseline.md)。

`--suite extended-core` 使用独立的 19 场景扩展包，包含结构化控制流、轮询、清理与多 API 依赖；
`--suite engine-additional` 使用 11 场景附加包，包含运行与请求预算、Finally、并发、嵌套跳转、固定子流和 Dataset；
`--suite native-api` 使用 12 场景公开产品 API 包，包含 Header 层级、历史 API 版本、错误信封与资源生命周期。
引擎附加包的 Dataset 文件及 native API 临时项目没有删除 API，两包应在其余场景完成后运行，其清理只能在真实销毁本批整个隔离栈后核实。
先运行并保留清理未完成的退出码 2，再严格停止所属栈，最后对同一批次执行最终核验：

```bash
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.run \
  --directory /private/tmp/flowtest-selftest-example \
  --output-dir /private/tmp/flowtest-native-api-results --rounds 1 --suite native-api
backend/.venv/bin/python -m scripts.selftest.local_stack stop \
  --directory /private/tmp/flowtest-selftest-example
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.run \
  --directory /private/tmp/flowtest-selftest-example \
  --output-dir /private/tmp/flowtest-native-api-results --rounds 1 --suite native-api \
  --finalize-disposable
```

第一步的退出码 2 只允许表示尚待本批资源销毁，其他诊断不得忽略。最终核验重新检查 Docker 中本批容器、网络和卷确实不存在；
不修改原始执行、不重新运行场景，也不删除 `evidence.pre-disposal.json`。每一步的完整日志和退出码应分别保留。
`engine-additional` 使用相同的 `--finalize-disposable` 流程，必须对它自己的原始输出目录另行核验。两包共用同一次准确的所属栈销毁，不能省略其中任何一包的最终核验。

每批生成以下证据，均只包含有界的合成白名单数据与凭据摘要：

- `mcp-catalog.json`、工具调用摘要和生成、编译、审核发布映射。
- `manifest.json`：执行前固定的期望、节点、构建、任务与策略身份。
- `evidence.json`：独立读取的执行、全部 attempt、Mock journal 和来源关系。
- `execution.junit.xml`：保留原始失败；故意错误断言仍是失败。
- `verification.json`、`verification.junit.xml`：独立期望判定及完整性。

本地结果为 `local_untrusted`；普通项目账号不能自行声明 `trusted_ci` 或写入正式 Required Gate。
退出码 0 仅表示该 manifest 的完整选择集符合期望；不完整或阻断退出 2，不匹配退出 1。
失败不通过自动重试覆盖；修复后新建输出目录，保留旧批次。

## 清理

运行期间仅删除本轮登记的 Mock 场景及业务临时资源。正式产物保留在隔离 A 中供检查。
检查完毕后，通过已冻结的 ownership 清理本栈容器、网络和数据卷，并删除本地私密配置。
命令先逐一校验归属；不会执行全局 prune 或按模糊项目前缀删除资源。

```bash
backend/.venv/bin/python -m scripts.selftest.local_stack stop \
  --directory /private/tmp/flowtest-selftest-example
```

## 检查边界

开发使用命名后端测试、Ruff、mypy 和受影响前端测试。真实 MCP 进程、隔离原生执行、CI 当前提交门禁、
真实宿主模型、浏览器主链及完整发布验收必须分别报告。离线单元测试和 Skill fixture 不能替代后四者。
