# 提案审核恢复与受限 Preview

本包使用真实 MCP SDK 2.2.0，通过 stdio 和 Streamable HTTP 各执行 6 个场景。只声明 `review_recovery_and_preview_only / local_untrusted`，不调用模型。

每种传输先经 MCP 导入本轮合成清理接口、生成 Design、建立固定 Contract Revision 的 Context，再提交明确编写的 Preview fixture。该 fixture 不称为未改动的生成 Case。覆盖以下边界：

- 未审核提案、生产分类目标拒绝；一次性审批固定最多 2 次请求、30 秒、并发 1；同键重放复用 Preview ID，新键复用审批被拒绝；真实 Graceful Cancel 和独立 Cleanup journal。
- Preview 始终保持用途为 preview，无 source Case/Plan Run；执行 JUnit 明确不代表正式用例。审批先于发布，Preview 通过不替代后续发布或正式运行。
- 发布响应体丢失后只 GET 查询同一工作流的唯一版本，不重发 POST。这是明确的客户端响应体丢失注入，不宣称该场景进行了 TCP 断链；真实传输断链由独立 transport-fault 包覆盖。
- 已审核提案遇到人工草稿修订必须拒绝应用；旧审批不能授权改变后的 Oracle；并发接受仅一成功、一明确冲突；已知部分接受状态持久保存并查询后仅续作剩余项，不重复物化。该局部续作不宣称进程崩溃；真实安装进程恢复由 initialization 包单独覆盖。

全包上限 500 次保守请求 admission、100 次工具、600 秒，每场景最多 180 秒。独立 O 核对 12 场景完整集合、原始调用及 HTTP 元数据、两组织隔离投影、来源、审批、版本、取消和清理。所属栈停止前不得最终通过。

当前版本 1.0.2。最初 1.0.0 把工作流发布 HTTP 状态误写为 201；公开路由与既有测试规定 200，因此修订为精确 200，并保留 [1.0.0](history/pack-1.0.0.json) 及失败尝试，不接受两个状态。1.0.2 另明确：本包通过公开 PATCH 修改名称和 Revision，会先触发语义快照冲突 `FLOWSPEC_TARGET_CONFLICT`；仅在 SQL 中改变 Revision 的旧表征属于不同前置条件。保留 [1.0.1](history/pack-1.0.1.json) 与原不匹配回执，新增公开接口表征确认该契约，不接受两个冲突码。开发中另外纠正了 H fixture：可移植 DSL 使用支持的默认安全策略，实际执行由更窄的 Preview 授权限制；Cleanup 覆盖成功、失败和取消。

```bash
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.review_boundary_run --directory /绝对路径/已初始化的专用栈 --output /绝对路径/新批次
```

处置前仅允许 `OWNED_ASSET_DISPOSAL_PENDING`。精确停止所属栈后，用同一参数追加 `--finalize-disposable`；原始绑定、H 来源及实际容器/卷/网络缺席必须全部匹配，独立 O 才能最终通过。
