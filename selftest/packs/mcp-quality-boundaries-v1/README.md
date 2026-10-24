# MCP 设计质量与不可信材料边界

本包只验收确定性 MCP，使用 SDK 2.2.0、协议 2026-07-28；不调用模型。18 个场景覆盖 stdio 与 Streamable HTTP 两种实际传输。

每种传输包含正常设计、空 Case 提案、需要审核的来源、生成截断、必需覆盖缺失，以及契约 description/examples 中的不可信指令、只读 scope 越权写入、生产目标限制、密钥引用元数据检查。设计质量规则固定必需场景种类和非零分母，独立 O 重新计算规则，不采信候选提供的 decision。

凭据场景分别调用 `inspect_project_readiness` 和 `discover_services`，从实际公开契约读取凭据就绪状态和端点 `secret_ref_count`，检查合成密钥值未进入返回数据。全包精确 68 次工具调用，共享上限 100 次工具、500 次保守 HTTP admission 和 600 秒运行期限。

本包不审核、发布或运行正式 Workflow/Case/Suite/Plan。只有两个 Design-only 提案保持 pending；独立、分页完整的只读投影核对 10 类正式资源的精确变更集合。设计成功不代表正式用例执行成功，执行 JUnit 明确 skipped，核验 JUnit 独立记录。

在已安装的专用目标上执行：

```bash
PYTHONPATH=.:backend backend/.venv/bin/python -m scripts.selftest.quality_run --directory /绝对路径/专用栈 --output /绝对路径/新批次
```

处置所属栈前仅允许 `OWNED_ASSET_DISPOSAL_PENDING`，退出码 2。精确停止该栈后使用同一参数追加 `--finalize-disposable`；完整绑定、当前 H 来源、原始身份和真实资源缺席均通过后，独立 O 才能返回 0。该批次仅声明 `generation_quality_negative_only / local_untrusted`，不替代真实宿主或发布验收。
