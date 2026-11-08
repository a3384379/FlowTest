# 契约变更与发布槽位自测

本包固定 ST-MCP-012 的契约变更、重新生成、预览冻结，以及 ST-MCP-040 的跨项目、未发布、指纹漂移和正确回填，共七项独立核验。原生执行共两轮；三个拒绝路径不会伪造额外执行。

入口为 [run_contract_delta.py](../../../scripts/selftest/run_contract_delta.py)。仅传入具有精确 ownership 的自测部署目录和全新输出目录：

```sh
python -m scripts.selftest.run_contract_delta --directory "$OWNED_STACK" --output "$NEW_RESULT"
```

H 通过公开 API 建立本包专用 A 项目和显式 foreign 项目。只读执行凭据仅限本包项目；既有 MCP 身份仍受现有权限限制。v1 由 MCP 导入，v2 经真实 MCP 预览后保留 `IMPORT_REVIEW_REQUIRED`，由独立 fixture reviewer 使用现有普通导入 merge 更新。两轮分别重新 inspect、generate、compile、审核发布 Workflow 与 Case，再固定 Suite、Plan 和正式 Run；v1 的冻结文件与结果保留。

Case 草稿允许引用未发布 Workflow；正式发布时必须以 `WORKFLOW_NOT_PUBLISHED` 拒绝。跨项目 Case 审核接受以 `WORKFLOW_NOT_FOUND` 拒绝，改动后的 Case 用旧 draft fingerprint 正式运行以 `TEST_CASE_DRAFT_CONFLICT` 拒绝。独立核验同时检查未新增执行和正确回填的两次正式执行。

总时间 600 秒、工具调用 100 次、保守 HTTP 请求上界 500。工具每次预留四次产品 HTTP 请求，其他 H 请求和两次原生请求单独预留；这不是外部网络硬限额。Mock 使用同一有绝对截止时间的共享预算，只允许本包合成命名空间。删除必须等原生 Plan 终态，并使用 nonce、fixture epoch 和 registration epoch 条件。

独立 O 子进程只接收冻结合成文件，不接收 H、A、B、Mock 或模型凭据。它使用[固定黄金](pack.json)和[只读核验器](../../../scripts/selftest/contract_delta_verify.py)，分别输出 `execution.junit.xml` 与 `verification.junit.xml`。JSON Schema 在本目录的 `schemas/`。

项目没有 DELETE API，必须等待整个自有隔离部署精确销毁。销毁前只有七项 matched 且唯一 finding 为 `OWNED_ASSET_DISPOSAL_PENDING` 时，exit 2 才表示待最终化。完成现有 owned stop 后，使用相同参数追加 `--finalize-disposable`，核对原 runner ID、卷、镜像、nonce 和完整 binding，并保留 `evidence.pre-disposal.json`。其他缺项、过期、未知结果或清理失败均不能通过。

ASGI 行为测试和合成捕获仅是本地验证。实际 Full、Compact、Standalone 部署须独立运行并绑定当次来源。审核方式为 `ci_fixture`；本包不证明真实模型、真实人工审核或全部 94 项验收通过。
