# 合成测试样例说明

这些 JSON 是开发计划的输入样例，不是已部署接口数据，不应直接发送到真实服务。API UUID 和版本是占位合成资产；运行测试必须在 harness/mock 或隔离测试数据库创建相应资产并替换/映射标识。

| 文件 | 目的 | 预期 |
|---|---|---|
| 01-linear | 基础开始/API/结束 | 用于选择、移动、基础删除恢复 |
| 02-conditional-branches | 条件 true/false 分支 | 两边必须完整；普通边不带条件 |
| 03-mapped-edge | A→B body 映射 | 删除撤销恢复映射；重连同步端点 |
| 04-extended-request | runtime_inputs、auth suppression、polling | 改一个 Body 字段不得丢其他字段 |
| 05-cleanup-phase | 无主流程连线的 cleanup 节点 | 不得误判必须从 main Start 可达；cleanup_for 原样保留 |
| 06-json-parse-mapping | 后端已有 json_parse transform | UI 往返保留；不改成 identity |
| 07-disconnected-local-draft | 故意断开的主流程 | 本地可继续编辑；服务端严格 WorkflowDefinition 应拒绝 |
| 08-capability-start | flow.start@2.0.0 的 legacy 兼容 | effective Start 保护；不可因 type=capability 就删除/复制 |

## 验证边界

本交付只对这些文件执行了 JSON 解析和独立的结构一致性检查，没有在 FlowTest 环境执行 Pydantic、服务资产解析、执行调度或真实接口请求。因此文件的“预期”是待开发阶段验证的断言，不是测试 PASS。

在后端测试环境使用 `WorkflowDefinition.model_validate(payload)` 验证图模型（07 预期拒绝）；再在现有 API/工作流测试 fixture 中验证服务级规则。API 配置解析可使用现有 `parse_node_config`。不得为使样例通过而放宽业务校验。
