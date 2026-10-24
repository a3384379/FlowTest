# MCP 生成用例检出合成坏目标

本包冻结三类目标故障：HTTP 200 业务码错误、上游依赖与下游结果不一致、HTTP 403 响应泄露固定合成资源。第三类仅证明拒绝响应内容契约，不能作为跨租户数据库授权验收。

H 通过真实 MCP SDK 导入契约、生成 Design、编译并提交原生流程和 Case 提案；审核者经现有审核、物化、发布接口确认。依赖场景仅补充显式请求参数和双射 Oracle ID 映射，保留全部生成断言的语义与原始设计指纹。

相同已发布 Workflow、Case、Suite 与 Plan 先执行正确目标，再执行坏目标，共两个正式 Run、六个执行、八个目标请求。两轮预期在第一次执行前封存。坏目标必须精确触发已冻结的 Schema 断言，错误码为 `WORKFLOW_ASSERTION_FAILED`、阶段为 `main`；鉴权状态错误、零请求、缺失断言、截断、来源变化与未确认清理均不能计为检出。

总期限最多 600 秒，共享最多 500 次请求和 100 次工具调用。两轮各输出原始执行 JUnit 与独立核验 JUnit；原始失败保留。默认审核分类为 `ci_fixture`，来源为 `local_untrusted`；本包不调用模型或宣称真实人工验收。

安全回执可单独复核：

```sh
python -m scripts.selftest.bad_targets_verify /absolute/path/badtargets-result.json --output-dir /absolute/path/reverification
```
