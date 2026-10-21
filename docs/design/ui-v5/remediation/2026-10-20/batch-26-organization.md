# 第二十六批：M24 组织治理

对应冻结审计 [F-ORG-01](../../audits/2026-10-19/complete-audit.md#f-org-01)、[F-ORG-02](../../audits/2026-10-19/complete-audit.md#f-org-02)、[F-ORG-03](../../audits/2026-10-19/complete-audit.md#f-org-03) 及[实施方案](../../audits/2026-10-19/remediation-plan.md#m24)。冻结文件未修改。

## 实施结果

- Runner、密钥安全、组织审计、支持包各自显示初次加载、失败、403 无权限及独立重试。错误呈现服务端标准消息和 Trace；失败或重新读取期间不显示旧数据或成功默认值。成员、服务账号、组织策略也使用各自读取边界，避免一个子域失败遮住其他子域。
- 密钥区仅在当前安全读取成功、能力名称、模式、重加密标识和阻塞字段共同满足原合同后显示“能力已确认”，使用信息态呈现；数据不足时不提供 Prepare / Apply / Rollback。保留系统管理员或组织 Owner 的原 `canRotate` 规则，Admin / Member / Viewer 不获得轮换操作。Runner 未读完整时禁用治理策略保存并说明原因。
- 组织审计按服务端 `page/page_size/total` 请求，支持时间、动作、操作者 UUID、资源类型和资源 UUID 精确筛选；筛选从第一页开始。保留原组织授权，新增两个过滤字段在服务层同时作用于列表与 total，并按时间、ID 稳定排序。
- 审计表格显示操作者、资源和已有 Trace；只读详情展示组织、项目以及服务端已经授权返回的 details。Trace 只读取已有 `details.trace_id`，未增加采集、日志、诊断或数据库字段。保留策略清理导致页码越界时，明确说明并提供返回首页操作。
- 切组织销毁旧组织工作区，重置审计页码、筛选、详情和成员草稿；旧组织一次性 token 也不会带到新组织。失败读取不混入前一组织的目录或详情。
- 系统管理员复用现有 `/users/search` 的真实搜索、分页和账号选择，显示名称与邮箱以区分同名用户。组织 Owner / Admin 仅搜索已经有权读取的本组织成员；添加其他已知账号保留高级完整 UUID 输入并解释边界，不调用系统用户目录，不新增目录授权。
- 本组织成员列表增加当前显示名、邮箱两个可选只读摘要字段，由原组织 `read` 授权后查询本组织成员关联用户；响应不返回密码字段。角色说明采用中文。成员提交等待服务端成功后才清空；404 / 500 时保留身份、所选角色和原列表角色，持续显示标准错误与 Trace；提交期间禁用表单和成员角色修改，阻止重复写入。
- 服务账号签发、轮换、撤销及 token 一次显示流程保留。已确认并关闭的 token 不会因安全读取重试再次出现。密钥加密、重加密、校验、事务回滚及审计实现未修改；无数据库模型、迁移、依赖或 CI 治理变更。

## 反例与检查

开发前已阅读工作树规则及 M24 冻结章节。先增加行为反例：前端首次 11 项失败、2 项原有行为通过；后端新增反例确认身份/资源筛选未生效，total 为 62 而预期 61，成员摘要缺失。修复后补充读取挂起、页外恢复、角色边界、切组织和重复提交验证；未修改测试超时、全局 mock 或覆盖率阈值。

实际执行：

- `make test-frontend-targeted TARGETS='["src/pages/OrganizationGovernancePage.test.tsx","src/pages/organization-governance-rotation.test.tsx","src/features/projects/DirectoryPicker.test.tsx"]'`：3 文件、29 项通过。
- `make test-backend-targeted TARGETS='["tests/test_organizations_api.py","tests/test_organization_governance.py","tests/test_key_rotation.py","tests/test_access_domain.py","tests/test_access_api.py","tests/test_errors_and_trace.py"]'`：6 文件、31 项通过。保留既有 `TestPlan` 收集警告，未处理无关历史警告。
- 变更后端文件 Ruff 格式检查、Ruff 检查通过；`uv run mypy app`：445 源文件通过。
- 前端全量 `pnpm lint`（含 `tsc -b --pretty false`）及 `pnpm build` 通过；本批修改文件 Prettier 和 `git diff --check` 通过。

覆盖的关键行为包括四个子域逐一 500 / 403 / 挂起 / 重试成功、能力字段不足、安全数据不可读时禁止操作、Admin / Member / Viewer 不可轮换、第六页可达、total 与过滤条件一致、已有 Trace 与只读详情、目录越界恢复、切组织拒绝读取时无旧详情、同名账号区分、低权限不请求全目录、成员失败保留身份和角色、成功清空、挂起期间重复点击不重复写入、已关闭 token 不因重试恢复。后端还运行现有真实密文重加密与回滚、账号生命周期、访问授权及标准错误 Trace 合同测试。

原始日志保存在本批工作树 `output/m24-organization-20261022/`，包括 `frontend-red.log`、`backend-red.log`、`extra-red.log`、`frontend-final.log`、`backend-final.log`、`frontend-lint.log`、`frontend-build.log`、`backend-static.log` 和 `format-check.log`。日志只涉及测试合成账号与固定测试 token，没有真实凭据。

## 改动文件

- 前端：`OrganizationGovernancePage.tsx`、`OrganizationGovernancePage.test.tsx`、新增 `OrganizationAuditPanel.tsx` 与 `OrganizationQueryBoundary.tsx`、组织 `organization-service.ts`。
- 后端：组织专属 endpoint、service、repository、schema，组织治理 service，以及 `test_organizations_api.py`；不涉及分布式执行面的共享文件。

## 真实浏览器验收交接

本批未运行真实浏览器，也未重配、重启或使用主代理共享 Compose / 浏览器会话。主代理整合代码后可在其隔离环境准备以下合成资料验证：

1. 两个组织，其中一个至少 61 条同动作审计，包含不同操作者与不同资源 ID；第一组织查看第六页、组合筛选、只读详情，再切第二组织确认页码与筛选重置。
2. 两个同名但不同邮箱账号，以及系统管理员、组织 Owner、Admin、Viewer 身份；验证系统搜索和本组织搜索边界、错误 ID 与失败重试、角色操作权限。
3. 通过测试路由拦截分别挂起及返回四个读取端点的 500 / 403，再解除拦截重试；安全失败时没有轮换操作，Runner 失败时不能保存默认治理策略。
4. 使用临时最小权限服务账号签发测试 token，确认后关闭，再重试失败的读取；确认 token 不重新显示。不得记录真实 token 或密钥材料，不执行真实密钥轮换作为页面失败态演示。

## 完成边界

F-ORG-01 / 02 / 03 达到本地开发、反例和针对性合同验证完成，可供主代理整合。未执行 `make check` 全量覆盖率、Compose 浏览器验收、Windows 包、真实 KMS / 生产账号轮换、远端最新提交门禁、合并或部署；这些不由本地 29 / 31 项通过推定完成。提交 SHA 由本批交付消息记录。
