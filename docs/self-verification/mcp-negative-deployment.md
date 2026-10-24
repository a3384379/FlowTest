# MCP 负向探针的既有隔离栈验收

入口只接收已经拥有、完成安装并通过 `StackBinding` 核验的 Full、Compact 或 Standalone 隔离栈。它不创建栈、不执行初始化、不调用模型。配置阶段只重新创建既有 runner，以加载受信 O principal 与限定用途的 probe grant；目标、数据卷、镜像、网络和其他角色必须保持原身份。

```bash
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.mcp_probe_run \
  --directory /absolute/owned-stack --output /absolute/new-protocol-result --pack protocol34
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.mcp_probe_run \
  --directory /absolute/owned-stack --output /absolute/new-governance-result --pack governance42
```

每次输出目录必须全新。H 使用既有安装者凭据登录，通过公开 API 创建两个不同组织的临时项目、独立评审者和限定权限机器账号。机器账号的撤销、短期过期和类型交叉拒绝均使用真实公开 API。令牌与密码只留在内存，独立 O 私钥仅保存在权限 0600 的私有状态文件；公开产物保存 ID、状态和摘要。

SDK 固定为 2.2.0。stdio 只执行已核验 runner 容器中的候选 MCP 入口；HTTP 使用同一候选容器的独立 gateway 和本机 loopback 字节转发。H/O 不导入候选 Python。协议 34 项只为 inspect 的运行形态字段派生 profile 专用 pack，其余冻结字面量与原始 pack 不变；派生 pack 摘要写入 manifest。

O 只访问 `/api/v1/agent/self-test-probes/{id}/inventory`。独立 grant 冻结两个项目、组织、nonce 摘要、manifest、binding、来源、镜像和绝对到期时间，不能用于原生 Run 取证。每页最多 100 项，完整快照最多 500 项、256 KiB、5 页；缺页、游标漂移、不完整投影或权限范围变化均拒绝。O 独立重算安全 DTO 的规范摘要，并逐步比对完整资产集合、提案唯一项、来源指纹、评审和物化关系。治理设计的完整规范化文档摘要及状态 200 Oracle 均来自事先冻结的合成黄金值，不能从返回结果学习。

每批总时限 600 秒、工具预派发上限 100。请求 admission 的上限为 500，模式明确为 `conservative_outbound_plus_candidate_rpc`：H 的每次 HTTP 出站与候选的每次 SDK RPC 都提前预留一个单元，HTTP 传输本身也预留出站单元。这是固定探针的保守上界，不是目标业务数据库计数或逐包网络抓取；任何拒绝计数非零均不能通过。

普通运行完成后预期暂以退出码 2 报告 `OWNED_ASSET_DISPOSAL_PENDING`。两个组织和项目没有模糊删除；必须由拥有者在同一批绝对期限内销毁整个精确拥有的隔离栈，再执行：

```bash
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.mcp_probe_run \
  --directory /absolute/owned-stack --output /absolute/new-protocol-result --finalize-disposable
```

finalizer 只读核对 ownership、原始 binding、已完成清理回执和 Docker 中同项目资源确实不存在，随后补写处置回执并重新运行 O。它不停止容器、不撤销账号、不重试未知删除。处置前证据另存 `evidence.pre-disposal.json`。退出码 0 表示本负向 pack 匹配，1 表示不匹配，2 表示证据或清理不完整；原始协议失败保留在 execution JUnit，独立核验结果另存 verification JUnit。

这些探针的声明始终为 `governance_negative_only`、`local_untrusted`。零原生 Run 不能被计为普通生成执行闭环完成。ASGI、单元及保留 wire 输入上的快照反证只证明对应本地行为；各运行形态必须另有当前候选的实际部署证据。
