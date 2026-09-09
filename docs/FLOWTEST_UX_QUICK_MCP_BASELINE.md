# 基础体验与轻量 MCP 实施基线

2026-09-10，实际 HEAD `591641b`，前后端声明版本仍为 `6.0.0-dev.0` / `6.0.0.dev0`。安装包与正在运行的服务版本未在本地环境核实。用户既有修改 `deploy/ruoyi/compose.yaml` 已保留。

两份 `FlowTest_*.md` 是本轮实施依据；阶段提示词中的要求只有在代码、测试和运行证据支持时才计为完成。

## 源码调查和阶段结果

| 问题 | 初始源码路径 | 当前结果 |
|---|---|---|
| 四种导出 | `backend/app/api/v1/endpoints/api_exports.py`、`backend/app/services/api_exports.py` | S1 已修复响应头、内容语义、上限、缺版本和 multipart 边界；真实大规模下载矩阵待 S7 |
| 环境选择与目标 | `frontend/src/features/api-console/use-api-console.ts`、`frontend/src/pages/RequestTargetsPage.tsx`、`frontend/src/features/workflows/use-workflows.ts`、`backend/app/services/request_targets.py` | S1 已统一项目/用户隔离选择和显式目标守卫；Celery/Runner 独立部署待 S7 |
| 环境生命周期 | `backend/app/api/v1/endpoints/api_assets.py`、`backend/app/services/api_assets.py` | S3 已增加编辑、归档式删除、引用/活动执行检查和前端管理抽屉 |
| 工作流生命周期 | `backend/app/api/v1/endpoints/workflows.py`、`backend/app/services/workflows.py` | S3 已增加归档式删除、测试计划/子流程/活动执行引用检查和前端入口 |
| 接口选择 | `frontend/src/flow/WorkflowDesigner.tsx`、`frontend/src/features/workflows/workflow-service.ts` | S3 已改为服务端分页、搜索、方法筛选和 `api_id + version` 固定引用 |
| 草稿与页签 | `frontend/src/features/workflows/use-workflows.ts`、`frontend/src/features/workflows/use-workflow-tabs.ts` | S4 已落地资源身份隔离的本地草稿 Store、恢复、冲突和删除清理；页签激活、关闭单个/其他/全部及 dirty 确认已覆盖，跨窗口冲突和实机 E2E 待验证 |
| 默认脱敏 | `backend/app/core/redaction.py` 及各 domain/service 入口 | S2 已完成安装/项目策略、OFF 短路、ON 兼容、任务快照和规范同步 |
| Quick MCP | `backend/app/services/mcp_simple_flows.py`、`backend/app/mcp/server.py` | S5 已注册真实强类型工具和 HTTP 入口，复用 FlowSpec 审查/幂等链，不自动执行 |
| Skill 与评测 | `skills/flowtest-generate-integration-flow`、golden fixtures | S6 已同步 quick 默认、deep 可选、工具 scopes、示例和评测预期 |

## 脱敏契约

- 默认安装策略是 `off`；项目未设置时继承安装策略，项目显式策略带版本号。
- OFF 时不调用敏感识别器，不改写 Token、Password、Cookie、Authorization、业务编号或样本值，也不因分类结果阻断；原有权限、加密、类型、表达式和 URL 校验仍有效。
- OFF 不会自动扩大日志 Body、样本或 LLM 输入采集范围。原本已授权且已开启的诊断采集遵循当前策略；ON 才执行已有遮盖逻辑。
- 排队任务在创建时记录 `redaction_mode` 和 `redaction_policy_version`，执行协调器、AI Runner、Standalone/Celery 和远程 Runner 使用该不可变快照。
- 迁移为 `20260909_0054_experience_policies.py`、`20260910_0055_task_redaction_policies.py`，Standalone SQLite 有增量兼容路径。

## 当前验证边界

后端静态检查、目标回归和前端检查记录在 [`FLOWTEST_UX_QUICK_MCP_ACCEPTANCE.md`](FLOWTEST_UX_QUICK_MCP_ACCEPTANCE.md)。以下项目只能在相应环境完成，不能用源码检查代替：

- 完整 Compose/Playwright 用户矩阵和两个真实 Mock 的所有部署档位；
- Windows 实机安装包、升级/回滚、MCP `tools/list` 和 quick 端到端；
- 20 次冷热性能采样、超过 100 条接口的大规模导出以及跨窗口冲突和浏览器实机多页签交互。
