# MCP 协议负向验收

该包冻结 34 个场景，使用锁定的 MCP SDK 2.2.0 和真实 stdio、Streamable HTTP 传输。
覆盖协议协商、未知工具、参数校验、业务错误、权限、跨组织、撤销和过期凭据、只读资源，以及两个身份交错和并发调用。
期望值来自冻结包；HTTP 200 或 `isError=false` 不代表业务成功。

从仓库根目录运行，输出必须是尚不存在的新目录：

```sh
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.mcp_negative \
  --local-loopback-only \
  --output /private/tmp/flowtest-mcp-negative-new \
  --python "$PWD/backend/.venv/bin/python" \
  --backend "$PWD/backend"
```

入口只启动自己的 loopback API、MCP 网关和私有 SQLite，不接受已有部署 URL 或凭据。
业务实体经公开接口创建，独立资产观察只对该新建数据库计数。该观察方式不适用于已有部署；
本包通过不能代表 Full、Compact、Standalone 或真实宿主验收通过。

整批共用 500 次 HTTP 入场、100 次工具派发、600 秒截止预算。预算包含失败尝试；
到期、缺项、重复、错误身份、缺少 trace、未确认清理均阻断通过。
公开结果包含冻结 manifest、受限证据、独立报告和原始/核验两份 JUnit。
私有进程日志和数据库保存在输出目录的 `private` 子目录，不能当作公开报告上传。

离线复核入口为 `python -m scripts.selftest.mcp_negative_verify --help`。
19 类篡改反证和实际 SDK 收据的具名回归位于
`backend/tests/test_selftest_mcp_negative.py`，不调用模型。

本版尚未覆盖非法 JSON-RPC 帧、超大消息、管道/套接字崩溃后的未知写结果，以及生成和审核恢复。
资源/提示中的合成文字只验证工具未产生副作用，不等于真实模型的提示注入防护验收。
