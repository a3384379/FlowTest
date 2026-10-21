# M22 审核路径 OFF 策略补充回执

对应冻结 [M22 审计](../../audits/2026-10-19/complete-audit.md#m22)、[整改方案](../../audits/2026-10-19/remediation-plan.md#m22)及[第二十四批回执](batch-24.md)。本次仅补齐审核物化时的 OFF 策略；开发基线为 `654b13ec658bc18dc5c3c05b5307831c5775023a`。

## 反例与修复

- OFF 下审核创建 Workflow 或 TestCase 时，字面量 `[REDACTED]` 被无条件占位符扫描误报为必须重新绑定运行值；更新已有键时会被静默换回旧值，新增键或改变嵌套列表时会被 422 拦截。
- 在已有值恢复函数入口读取现有请求范围策略，OFF 直接返回已授权的拟写入值，不进入占位符判断、递归扫描或替换；两处创建守卫也仅在 ON 执行。生产代码改动仅 6 行差异。
- 保留更新时未提供运行字段沿用现值的语义；ON 仍恢复已有占位符、拒绝未知占位符和含占位符列表的结构修改。继续使用既有编辑授权、目标快照冲突和标准错误 Trace。
- 未增加全局可变状态、采集、日志、Secret 读取、引擎或共享写路径改动，也未修改冻结审计、冻结方案或共享进度。

## 行为证据

新增 `backend/tests/test_ai_change_set_redaction_policy.py` 共 17 项公开接受 API 用例：两种资产创建/更新、已有/新增字段、Workflow 嵌套列表与完整字面值、显式编辑与直接接受提案、省略运行字段、ON 恢复与列表守卫，以及同一客户端交替访问 ON/OFF 项目。断言实际持久化草稿值；拒绝时核对错误码、Trace、pending 状态和目标未变化。

修复前最终反例运行为 10 失败、7 通过；已有键的静默替换与创建/新增字段 422 均被复现。首轮测试夹具把未规范化的 Workflow 输入与存储规范化结果直接比较，修正为读取实际基线；首轮修复后交替项目用例遇到夹具草稿重名，改为按动作区分名称。上述失败日志全部保留，未以重试或放宽断言掩盖失败。

实际运行：

- `make test-backend-targeted TARGETS='["tests/test_ai_change_set_redaction_policy.py","tests/test_quality_intelligence.py","tests/test_redaction_policy_off.py"]'`：68 项通过。
- `uv run ruff check app/services/ai_change_sets.py tests/test_ai_change_set_redaction_policy.py`：通过。
- `uv run ruff format --check app/services/ai_change_sets.py tests/test_ai_change_set_redaction_policy.py`：通过。
- `uv run mypy app`：445 文件通过。
- `git diff --check`：通过。

完整日志保留在本工作树忽略目录 `output/validation/m22-off-policy/`。实现提交 `a88a8464a2eb7c2e4fa48e90b11769ae64edef59` 的原测试结果为 `08-targeted-final.log`（68 项通过、16 项 SQLAlchemy 警告），静态检查为 `09-ruff-final.log`、`10-format-final.log`、`06-mypy.log`。

后续独立测试修正将全部合成变更项绑定实际 AI Job 与 AISuggestion，并将项目策略固定到 Job，符合正常生成提案的关联结构；没有修改生产兼容逻辑、过滤警告或放宽断言。相同三个具名文件重新运行 68 项通过、0 警告（11.58 秒），完整日志为 `11-linked-suggestion-targeted.log`；新测试文件 Ruff 规则和格式检查通过，日志为 `12-linked-suggestion-ruff.log`、`13-linked-suggestion-format.log`。生产代码未变化，原 `mypy app` 结果继续对应相同生产源码；未把旧完整运行结果改称为新测试树的完整验证。

## 完成边界

本次独立局部回归与自审未发现该修复的残余实际缺陷。未运行完整后端/前端门禁、Compose、浏览器、外部模型、GitHub 当前提交门禁、合并后 CI 或发布验收；这些结果由整合阶段另行记录。本回执不扩大第二十四批已声明的完成范围。
