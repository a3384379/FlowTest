> 历史记录：以下仅描述当时状态，不作为当前通过证据或本轮操作指令。当前状态见 [current-validation.md](current-validation.md)。

# S5 与非模型验收续作

2026-10-24 用户要求继续完成剩余 S5 及全部不依赖模型的验收，完成前持续推进；真实 Host/LLM 和付费模型 API 保持关闭。本记录是开发过程记录，最终通过必须对应新的固定源码及全部适用形态，不沿用 final27 放行。

## 已完成的开发与检查

- 新增 `s5-native-v1`：合成文件原生 multipart 上传、下载与文件断言，独立只读客户端下载本轮 artifact 并核对内容、SHA-256、长度、content type 和项目归属；文件回收要求精确所属栈移除。并行 Cookie 使用两个分支、各自客户端、确定性双分支屏障，核对六条请求及峰值并发 2，只采集合成 Cookie 的 left/right 值，不采集任意 Cookie。
- 新增 worker claim 租约、心跳与过期收敛；结果未知的写请求不重放，已完成的结果保留，未知执行以 `TEST_PLAN_WORKER_LOST` 失败。新增 Alembic `20261024_0068` 升级/降级及既有 Standalone 列升级路径。迟到的旧 worker 不得覆盖失效状态。
- 固定 CI 基线增加为 10 批，Full/Compact 另有独立 worker 故障波次，Standalone 明确不适用 Celery 故障波次。测试部署的精确 worker 命令启用嵌入式 beat，以实际执行 15 秒一次的租约收敛；不依赖人工修改数据库使其通过。
- 后端 worker/调度/任务 API/迁移联合 49 项通过；进一步工作流、调度、结构控制和新 S5 联合检查 202 项通过，`mypy app` 484 文件及 H/O 193 文件通过。初版心跳收尾竞态、SQLite ORM 时间比较、过期完成及取消后继续准备缺陷先由测试复现，再通过完成阶段标识、SQL 同步策略、owner/有效期条件和串行化取消/准备修复。
- Mock 42 项通过；原生文件/Cookie 的实际 API、引擎和独立 O ASGI 检查通过，包含文件内容及 Cookie 篡改拒绝。CI/新 S5/schema 联合检查 87 项通过，导出 schema 28 份已同步；额外 CI worker 失败/回收反证 17 项通过。FlowTest B 自身文件 API 已新增独立原生包，双应用/双数据库 ASGI 检查通过，B 的只读用户独立下载并校验本轮新 artifact。

## development29 当前应用构建实测

应用来源 `6f850db8a885ad152811710dcb4e546bbe5903ade5d67c26c9b02b5de4677593`；完整逐文件快照位于 `output/selftest-validation-20261024-s5/development29/sources/`。此处是开发阶段证据，后续 H/O 扩展后须重新固定全部来源。

- Compact：`/private/tmp/flowtest-s5-workers-compact29-run1` 四项真实 worker 故障，`/private/tmp/flowtest-s5-native-compact29/round-1` 三项原生文件/Cookie，`/private/tmp/flowtest-s5-product-files-compact29/round-1` 一项 B 自身文件 API；所属 nonce 栈移除后各自独立 O 退出 0。清理前退出 2 的原始报告保留。
- Standalone：`/private/tmp/flowtest-s5-native-standalone29/round-1` 三项原生文件/Cookie、`/private/tmp/flowtest-s5-product-files-standalone29/round-1` 一项 B 自身文件 API 已实跑，原始执行均通过；精确回收及 Full 对应实测继续进行。

## 已封存的开发阶段实测

这些是心跳收尾和过期完成补强前的应用来源 `03417a4155e6f930551f2b2b1b249e81f40a913f7c05edf7eff23ccc7e198838`，不代表最新代码通过。

- Standalone：`/private/tmp/flowtest-s5-native-standalone28/round-1`，3 个原生场景均 passed，所属栈移除后 O 退出 0。第一次收尾因 CLI 未纳入新 suite 的允许集合而拒绝，原日志保留，补齐范围后成功，不放宽处置约束。
- Full：`/private/tmp/flowtest-s5-workers-full28-run1`，4 个场景实际执行及最终 O 退出 0。双 OS 进程在原子 claim 前经管道屏障同步，只有一份原生执行；重复 Celery 投递没有重复业务请求。两种 SIGKILL 场景分别只发出 1/2 个请求，并由真实 60 秒租约与周期任务收敛为原始 failed，错误码精确为 `TEST_PLAN_WORKER_LOST`。原始失败与独立 matched 分开。
- 两套专用栈已按各自 nonce 停止；日常环境基线在 `/tmp/flowtest-s5-daily-before.txt`。未清理日常容器或镜像。

## 仍须完成

1. worker 波次的 CLI/O/CI schema、失败与反篡改回归；修复后的 Full/Compact 新镜像实际故障验收。
2. S5 原生包在最新 Full/Compact/Standalone 的完整采证与精确回收，以及新固定来源的完整本地检查。
3. 逐项补齐账本尚未完成的非模型产品 API、初始化、权限、运行/取消/观察截止、反误绿、来源、CI 策略、保留期和真实浏览器验收；不能用单元或 ASGI 通过代替部署验收。
4. 按适用能力核对 S5 稳定/候选交叉矩阵和发布形态，区分远程受信门禁、Windows 原生环境与本地 bootstrap review 的证据；缺失环境或授权不得写通过。
5. 更新完整验收账本、全部 schema、当前验证/交接和公开证据白名单。模型相关实际调用、真人审核不能由夹具补成通过；模型调用数维持 0。
