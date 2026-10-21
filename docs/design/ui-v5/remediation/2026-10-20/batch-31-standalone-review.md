# Standalone 审核基线兼容补修回执

日期：2026-10-22。开发基线：`1f720d581ae7679356aea6f7382a54f230266a3a`。范围为 M22 新增 `review_baselines` 在已有 Standalone SQLite 安装中的启动兼容。

## 问题与最小修复

已有完整 S62/FlowSpec 数据库可能仅缺少 0065 新增的 `ai_change_sets.review_baselines`。`Base.metadata.create_all` 不补已有表的列，原 Standalone 启动入口也未补该列，因此启动后 ORM 查询变更集会报 `no such column: ai_change_sets.review_baselines`。

`backend/app/core/standalone_schema.py` 在既有增量补列流程中复用 `_add_column_if_missing`，添加 `JSON NOT NULL DEFAULT '[]'`。旧行获得空列表；已有冻结值保持不变。没有把该列加入 FlowSpec 旧表重建判断，没有修改 Alembic 0065 的可逆升降级、版本标记或升级脚本合同，也未新增扫描、脱敏、日志或采集。

## 行为反例与验证

新增 `backend/tests/test_standalone_ai_review_baselines.py`：先用完整当前模型建立真实 SQLite 数据库，保存 AI/MCP 变更集、变更项、来源、审批和物化字段，再只移除该新增列，确认完整旧结构无需重建。通过真正的 `initialize_standalone_database` 入口启动后，ORM 可读取两类旧记录，基线均为空列表，所有原字段逐项保持，外键检查通过。随后保存包含 OFF 授权原值的新冻结基线，重复启动两次，验证新值和既有证据均保留。首次启动与后续启动分别比较快照，允许人工保存时合法更新 `updated_at`。另有真实新安装启动反例；既有 pre-S40 重建和迁移升降级测试继续执行。

修复前反例准确失败于 ORM 缺列，新安装用例通过；完整红灯日志保存在本工作树 `output/validation/batch31-standalone-review/red-startup.log`。

执行的具名测试：

```sh
make test-backend-targeted TARGETS='["tests/test_standalone_ai_review_baselines.py", "tests/test_standalone_runtime.py", "tests/test_standalone_transfer.py", "tests/test_ai_review_baseline_migration.py", "tests/test_quality_intelligence.py"]'
```

- 5 文件、78 项通过，覆盖已有 Standalone、新安装、pre-S40 重建、便携数据转移、0065 升降级和 AI 审核关联行为。最终完整日志：`output/validation/batch31-standalone-review/targeted-final.log`。
- 修改的 Python 文件 Ruff 格式和规则检查通过；`mypy app` 检查 445 个源文件通过；`lint-imports` 的领域隔离合同通过。对应日志同目录保存。
- 首次目标清单含本开发基线不存在的 `test_ai_change_set_redaction_policy.py`，目标检查在执行 pytest 前拒绝，已保存 `targeted.log`；随后改用本树实际存在的上述 5 文件，没有复制其他工作树实现或放宽检查。

## 边界

本次仅修改启动补列、专属测试及本回执，未操作共享验收树、数据库或浏览器。未运行全量后端、Windows 打包、Compose、真实已安装 Windows 数据库升级或最新远端门禁。整合后生产后端树已变化，需由整合负责人重新执行完整后端与适用正式门禁；旧树的全量通过记录不能替代本次验证。
