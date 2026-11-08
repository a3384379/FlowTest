# 运行故障验收包

精确对应用户《源码证据与验收矩阵》5.4 的 ST-RUN-001/002/003/005/006，共 15 个独立变体。仅用于精确归属的独立 Full/Compact profile；包本身存在不代表已运行，日常栈、源 Standalone/UI 栈均拒绝。

- 预期位于 `expectations.json`，在任何启动之前冻结摘要。原始执行状态、独立验证结论与观察器进程状态分别记录。
- 每个变体创建独占 Mock namespace 和固定 Workflow → Case → Suite → Plan。API 的非幂等 POST 含唯一 marker；最大 100 请求、600 秒，不重试非幂等变更。
- RUN-001 比较同一固定计划的 manual/ci 两次 Run，必须不同 ID、相同固定资产摘要且所有子项终态。
- RUN-002 的 Plan 启动有效请求恒为 `{}`，因此“不同 payload”用现有 CI Workflow 启动接口的 `runtime_variables` 实测。并发结果只允许同一 ID 或精确 `IDEMPOTENCY_IN_PROGRESS` 后同 key 恢复；未观察到 pending 不冒充该分支通过。丢响应代理在实际请求已经返回后丢弃响应，只发送一次真实请求，再用相同 key 恢复；不换 key。
- queued 阶段仅在精确校验归属的 Full/Compact runner worker 暂停后启动。Standalone 没有独立 worker 容器，不能冒充 queued 变体通过。恢复必须在 finally，停止前再次校验 project/nonce。
- RUN-003 running 取消先以独立 journal 看到 first，随后取消；follow 必须不出现，cleanup 是否出现由冻结策略决定。force 仅调用已有 workflow cancel API，不自行改写 Plan/Execution 状态。
- RUN-005 使用独立 observer 子进程；到期返回 incomplete/2，故障注入在已保存实况后以 70 退出。独立 watchdog 后续取消并等全部原生终态，再删除 fixture。观察器退出绝不能把仍 running 的原生任务改为 passed。
- RUN-006 的未指定版本输入在公开Workflow发布时会自动固定API当前版本；该输入对照仅表征发布规范，不能声称正式执行保持未固定API。发布前分别冻结输入图摘要与预期published固定图摘要，`publication-binding.json`记录确切v1绑定，绝不运行后反推。
- RUN-006 先冻结预期，再暂停 worker 入队，然后增加 API v2/修改独占环境合成变量，恢复 worker 后读取 actual API binding/snapshot。unpinned 只做 characterization；正式 pinned 必须仍 v1；环境漂移必须阻断独立核验，不假设 Plan target_snapshot 冻结全部依赖。
- 所有失败与未知结果保留回执，需人工检查或 bounded watchdog。不得因最后一次成功覆盖前次失败。只销毁独占 profile，不触碰日常服务。

实现入口为 `python -m scripts.selftest.run_runtime_faults`，固定预期、driver、observer和构建身份在变更前冻结。所有15项结果行先写NOT_RUN；未完成不会缩小分母。单元行为测试使用 fake transport 仅证明 driver/独立判定，不作为真实部署验收。

实际独立 Compact final8 attempt3 已完成15/15 matched、36个业务请求；原始证据保留在 `/private/tmp/flowtest-runtimefault-compact-20261023-attempt3-results`。这只证明该次绑定的镜像、pack 与 draft driver，不是仓库新入口的重验，也不是全部发布验收。离线公开API角色与发布规范测试另行验证，不混入部署通过计数。

待独占Full/Compact新栈就绪且根任务给出运行窗口后，使用仓库Python与显式PYTHONPATH运行 `python -m scripts.selftest.run_runtime_faults --directory <owned-profile-dir> --output-dir <new-dir>`。禁止以日常栈或原Standalone UI源栈为目标。执行后仍需独立owned stop验证全部容器/卷/网络消失；本driver不擅自停止调用方栈。
