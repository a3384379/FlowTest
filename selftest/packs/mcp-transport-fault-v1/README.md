# MCP 真实传输故障包 1.0.1

冻结分母为 14 条，SDK 固定为 `mcp==2.2.0`。每批最多 600 秒、500 次保守出站/RPC 预算、100 次工具调用。此包的范围是 `transport_fault_negative_only`，来源是 `local_untrusted`；没有原生 Run，不作为普通生成闭环通过证据。

| 验收项 | 真实触发 | 适用传输 |
| --- | --- | --- |
| ST-MCP-004 / bad_jsonrpc | SDK 发出请求后，专属代理向候选网关转发损坏 JSON、错误 JSON-RPC 版本；保存实际 HTTP/RPC 错误和原请求 ID 的关联 | HTTP 各 1 条 |
| ST-MCP-004 / oversized | 原生 SDK 直接提交 `expected_contract_version` 的 81 字符值，服务端字段上限为 80 | stdio、HTTP |
| ST-MCP-007 / inactive | 通过公开 API 创建专属用户及服务账号，再停用创建者；服务账号仍 enabled 且未 revoke | stdio、HTTP |
| ST-MCP-008 / timeout | 请求确实转发并收到服务端回包后，专属代理扣留回包超过 SDK 单次期限 | stdio、HTTP |
| ST-MCP-008 / pipe_break | 专属标准输出 OS 管道真实关闭 | stdio |
| ST-MCP-008 / socket_break | 专属 loopback TCP 连接真实关闭 | HTTP |
| ST-MCP-008 / server_crash | 真实 SIGKILL 本次专属候选 MCP 服务进程，核对 nonce、PID、Linux `/proc` start ticks；不终止业务 API 或容器 | stdio、HTTP |
| ST-MCP-008 / unknown_mutation | 固定幂等键只提交一次真实 Design 提案，收到完整服务端回包后丢失客户端回包；原 SDK 错误保留，O 只读恢复精确提案 ID 和冻结 Design 摘要 | stdio、HTTP |

`oversized` 只证明字段边界，不证明消息总字节限制。公开 API 没有独立机器账号 suspend，本包不能把 creator inactive 冒称机器 `enabled=false` 且未 revoke。其他排除项见 [exclusions.json](exclusions.json)。

`pack.json` 的黄金值来自冻结 SDK、产品公开 DTO 和显式合成 Design 契约；`normalized-design.golden.json` 不从本轮执行结果生成。现代 SDK 对错误 JSON-RPC envelope 返回 `-32600`；JSON 解析失败返回 `-32700`。HTTP 连接中断保留 SDK 原生 `RemoteProtocolError`，不伪写成原生执行超时。

## 已有隔离栈入口

仅使用已经初始化并通过 ownership/build/profile 核验的自有隔离栈。命令不会 bootstrap、启动栈或调用模型：

```sh
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.mcp_fault_run \
  --directory /private/tmp/owned-stack --output /private/tmp/fault-attempt-new
```

运行会公开创建本包专属的两个组织/项目，通过受信配置 reload 追加独立 O grant 和 principal，原有 principals/grants 保留。它会重新创建 runner 容器，因此必须排在其他包冻结 `required_disposal` 的 runner ID 之前。结束前预期只有 `OWNED_ASSET_DISPOSAL_PENDING`，14 条场景必须全部 matched。随后统一精确销毁自有栈，再调用：

```sh
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.mcp_fault_run \
  --directory /private/tmp/owned-stack --output /private/tmp/fault-attempt-new \
  --finalize-disposable
```

独立 O 可单独重跑：

```sh
PYTHONPATH=. backend/.venv/bin/python -m scripts.selftest.mcp_fault_verify \
  --manifest /private/tmp/fault-attempt-new/public/manifest.json \
  --evidence /private/tmp/fault-attempt-new/public/evidence.json \
  --authority /private/tmp/fault-attempt-new/public/authority.json \
  --output /private/tmp/fault-independent-new
```

O 不导入产品、生成驱动或引擎 verdict。它核验精确场景/请求/尝试集合、完整分页和十类资产、实际 SDK/frame/进程清理回执、未知变更只新增一个固定语义的待审 Design，以及正常资产不变。缺回执、零请求、重复投递、旧 nonce/build、错误 PID、错误业务内容、过期或清理不完整都非零。原始 SDK 执行 JUnit 保留失败，独立核验 JUnit 单列匹配结果，批次全局 finding 也生成失败 testcase。

只保存合成字段的 ID、状态和摘要，不保存令牌、请求头、完整会话或响应正文。stdio 的 `forwarded_bytes/digest` 指规范化 JSON frame，不含换行分隔符。安全公开归档仅复制身份摘要、verification 和双 JUnit；`manifest/evidence/authority`、私钥和本机配置留在私有目录。

`tools/list` 是工具目录元数据，HTTP 和 stdio 都单独限制为 1 MiB；普通工具与写回包保持 256 KiB。读取按 chunk/有界 readline 限制，不在收到完整大包后才检查。目录正文只在转发内存中存在，不写入产物。

## 1.0.0 契约勘误与失败记录

初版保留在 [pack-1.0.0.initial-contract.json](pack-1.0.0.initial-contract.json)，规范 JSON 摘要为 `e3b5dcbd05f8b3bd0b5eb7f584491df0159b7e04b6b77ab195bba33530af7526`。它错误地把两个 inactive 场景的 SDK `isError` 写成 true。已有冻结协议包 ST-MCP-005/007，以及 `backend/app/mcp/server.py::_tool_payload/_error_payload` 的既有契约都明确：应用拒绝作为 `data.error` 返回普通工具结果，SDK 位是 false。1.0.1 精确纠正为 false，仍必须是 `MCP_AUTHENTICATION_REQUIRED`、真实 trace、完整请求/进程回执和零资产变更；没有扩大允许结果集合。原始 JUnit 也必须把非空业务错误码记作失败，不能依据 SDK 位把应用拒绝变绿。

Standalone20 的 attempt1/2 分别因 HTTP/stdio 目录元数据被旧 256 KiB 限制错误阻断；attempt3 完整收集 14 条，12 matched，两个 inactive 因上述契约错误 mismatched。这三份历史产物保持原样。目录修复有真实 400 KiB 成功、超过 1 MiB 仍拒绝、普通工具大回包仍受 256 KiB 限制的表征。后续实际结果以新版本、新摘要和新 attempt 独立记录，不能覆盖这些失败。

## 验证层级

`test_selftest_mcp_fault_transport.py` 使用真实 SDK、OS 管道、TCP 和专属服务子进程验证传输机制；测试夹具不是候选产品验收。`test_selftest_mcp_fault_setup.py` 验证公开 API 停用身份。`test_selftest_mcp_fault_verification.py` 的合成 DTO 只验证 O 反绿规则，不冒充部署通过。Full/Compact/Standalone 的实际部署证明另由真实运行产物记录。
