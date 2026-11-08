# MCP 治理负向包交付

这是独立 `mcp-governance-negative-v1` 1.0.0 冻结包，42 个场景（stdio 和 Streamable HTTP 各21），使用锁定 MCP SDK 2.2.0 调用真实网关和公开 REST。它验证提案、幂等、权限及审批边界，**不是普通 MCP 生成并执行的闭环成功报告**。报告固定 `claim=governance_negative_only`、`trust=local_untrusted`。

当前入口只接受 `--local-loopback-only`，只启动本次自有的临时 API/gateway 进程与SQLite；不连接既有部署、不调用模型、不启动 Docker。所有授权值只在内存或临时子进程配置中，public 证据只包含白名单摘要、UUID、状态和严格计数。十种业务资产的只读 SQLite 总计数只适用于该自有本地进程；部署版须改用独立 purpose/grant 的公开只读分页 API，不得以此本地结果填 Full/Compact/Standalone 通过。

单批冻结上限500 HTTP admission attempts、100 SDK tools/call dispatch attempts、600秒。成功场景末端资产精确为6个提案、2个合成TestDesign、2个审批，其余Workflow/版本/Case/版本/Plan/Run/Execution均0。预期从冻结JSON来，观察从实际 SDK+REST/独立只读采集来；SDK业务错误的raw failed保留在 execution.junit.xml，独立预期匹配单独写 verification.junit.xml。

## 调用

```sh
PYTHONPATH=. backend/.venv/bin/python -m scripts.selftest.mcp_governance_runner \
  --local-loopback-only --python "$PWD/backend/.venv/bin/python" \
  --backend "$PWD/backend" --output /private/tmp/flowtest-governance-new-run

PYTHONPATH=. backend/.venv/bin/python -m scripts.selftest.mcp_governance_verify \
  --manifest /private/tmp/flowtest-governance-new-run/public/manifest.json \
  --evidence /private/tmp/flowtest-governance-new-run/public/evidence.json \
  --output /private/tmp/flowtest-governance-new-verification
```

输出目录必须全新；失败保留 partial.json、已生成的manifest与自有进程日志，并返回2及JSON/双JUnit。验证不匹配返回1；缺项、无效契约或过期返回2。重复运行不会覆盖旧目录。评审者是独立fixture用户，不能称真人审批。

## 已实际运行的证据

- `/tmp/flowtest-mcp-governance-draft/run-final/public`: 最终42个真实SDK/REST场景，独立O exit0，102 HTTP admissions/22 tools/call，两个transport都完成，自有进程清理完成。
- `/tmp/flowtest-mcp-governance-proof-20261023/proof.json`: baseline exit0及34个实际CLI篡改副本，均精确非零且含对应finding，运行时未过期，原manifest/evidence SHA不变，全部有双JUnit。
- `/tmp/flowtest-mcp-governance-draft/targeted-final.log`: 28个具名/参数化测试通过。
- `/tmp/flowtest-mcp-governance-draft/mypy-final.log`: 4个新H/O模块类型通过。
- `/tmp/flowtest-mcp-governance-draft/ruff-final.log`: Ruff通过；临时树测试文件因在项目根外，S101例外按真实backend/tests规则等价处理。合入后应从backend工作目录正常复查，无需扩大忽略规则。

表征日志保留先前无效Oracle请求、跨transport重名及SDK隐式tools/list造成的H缺陷，以及独立O重复回执/时间/提案文档漂移反例；未修改golden掩盖。

## 边界

ST-MCP-013/016/017/018/019/021 的相关变体由该包实现；只覆盖固定合成TestDesign及受控写入，尚未把所有ST-MCP-012–022/全94父项或341变体宣称完成。注入字符串只验证作为数据不产生提案之外的副作用，不宣称真模型抗注入。协议协商通知、外部Host、故障恢复等仍以验收ledger具体状态为准。
