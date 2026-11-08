# 错误断言独立审核

此包对应 ST-MCP-014。先通过真实 MCP SDK 生成正确 Design、编译 Workflow，再明确构造四份专用负向产物，分别删除 Schema 断言、改成只检查无关业务字段、改错比较符、以同一响应充当动态期望。五份产物都经隔离 fixture 审核、发布 Case / Suite，并执行普通 Plan Run。

冻结黄金要求五次原生执行均为 `passed`，独立审核仅接受正确对照，并拒绝另外四份产物。这证明原生成功不能替代关键断言语义审核。负向变体不是正常生成器的输出，也不构成正式自测全范围通过。

独立审核逐项核对冻结 Oracle、来源节点、表达式、比较符、Schema 类型、静态与动态期望来源，以及 Case、Suite、Plan、Execution 和目标 journal 的完整映射。公开返回会补回模型默认空字段，发布 fingerprint 对照原始执行 fingerprint；另保存公开 definition 的独立摘要，不混用两种序列化的摘要。

运行入口：`python -m scripts.selftest.semantic_run --directory OWNED_STACK --output NEW_OUTPUT`。支持 `--transport stdio` 或 `--transport streamable-http`。每批不超过 600 秒、100 次工具调用和 500 次请求；共享 H 请求上限 392，额外保留 100 次工具后端调用及 8 次原生和元数据请求。

生成资产只能通过完整销毁本轮隔离栈清理，销毁前核验返回 2。观察到精确归属的容器、卷和网络已销毁后，执行同一入口的 `--finalize-disposable`；独立重核验入口为 `python -m scripts.selftest.semantic_verify --manifest MANIFEST --evidence EVIDENCE --output NEW_OUTPUT`。始终分别输出原始执行和独立核验 JUnit，首次采证与销毁前证据保留。

真实模型、远程 CI 合并门禁和生产发布均不在本包的通过声明内。
