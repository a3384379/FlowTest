# ADR 0052：MCP 零接入的连接、身份与权限契约

状态：S61A 实现；后续写入契约冻结，尚未开放。

## 决策

S61/S62 沿用应用网关、ServiceAccountService、ImportService、AIChangeSet、ChangeRegression
和 Preview 生命周期，不建立第二套权限、凭据或执行系统。首次签发仍由现有已认证人类在组织管理
入口确认组织、Scope、范围和有效期；日常机器调用独立于浏览器会话。

优先实现 `flowtest-mcp setup`：仅检查用户显式指定环境变量中的已签发机器账号，输出引用环境
变量的 Codex 配置模板；不签发账号，不修改用户配置，不读取 Docker、.env、Cookie 或本机密码。
setup 的应用网关认证检查不等于宿主 MCP 传输或真实模型验收，两者分别记录。
不再支持进程参数 `--token` 明文入口，改用 `--token-env-var`，参数错误不回显原始值。

stdio 仅使用其显式进程配置；指定变量为空不得回落到另一变量。Streamable HTTP 仅使用本次请求
Bearer，缺失或非 Bearer 时不得继承进程账号。HTTP CLI 不加载共享机器令牌。

`flowtest.inspect_connection(request)` 无需 project_id。严格输入、未知字段拒绝；身份有效且
组织可用后才返回组织信息、Scope、版本、Feature、运行档位和动作组。不得把账号创建者的管理
权限当作机器账号权限。认证失败不枚举组织，输出安全诊断和 trace_id。旧错误 code 保留，新增
connection_diagnostic 区分认证、过期、Scope、网络、版本和 Feature，不能把所有错误都转成登录。

## 冻结工具与 Scope 映射

下表是实施契约，不是当前 tools/list。S61A 仅新增 inspect_connection（总数 39）；写 Scope
随对应实现和测试上线才加入签发 allowlist，避免提前授予无定义的权限。

| 阶段 | 工具（统一 `flowtest.` 前缀） | Scope / 应用能力与限制 |
| --- | --- | --- |
| S61A | inspect_connection | 有效 ServiceAccount；仅检查自身，无项目资产读取权 |
| S61B | ensure_project、ensure_test_environment、ensure_service_target | mcp:project:bootstrap；组织内空测试项目/新增 test 或 sandbox 元数据；已有资源仍执行项目访问/编辑授权 |
| S61C | preview_contract_import、commit_contract_import | mcp:contract:import；受限预览及选定新增接口；更新/覆盖/删除需精确 Diff 与人类批准 |
| S61D | inspect_project_readiness、find_assets | mcp:read；强类型有界读取，不暗中创建 Context 或扫描网络 |
| S61D | check_service_target | mcp:project:bootstrap；已登记测试 Endpoint 的有限连通性，不授权任意出站目标 |
| S62A | prepare_change_regression | mcp:regression:prepare；既有 ChangeRegression 分析准备，不能 approve/execute |
| S62A | propose_test_plan_update | mcp:test-plan:propose；既有 AIChangeSet 待审核建议，不能直接改发布计划 |
| S62B | cancel_preview | mcp:preview:execute；已授权 Preview 的 Graceful Cancel，保留 Cleanup；无生产/强制取消 |

已有 mcp:read/write/evidence:write/flow:propose/preview:execute 不静默扩权。新 Scope 不映射为
通用管理员或全局 create_project，也不修改 Viewer 拒绝创建项目的 H0 规则。组织由账号固定，
禁止传入其他组织来选择身份。已有项目的 MCP 资产授权走服务账号专用分支：以
`service_account_id`、账号固定组织和对应 MCP scope 判定，不读取账号创建者的 `is_system_admin`、
项目成员或团队角色；跨组织项目统一返回不可枚举的 404。当前 S61A 的账号授权粒度是组织内、
按账号 scope 的明确机器授权，不代表获得组织管理员或项目成员身份；S61B 再补充首个项目创建及
更细项目范围的显式 grant/幂等设计。新项目 Owner 规则和来源审计在 S61B 以显式授权主体实现。

## 组织级初始化的存储前置约束

当前 IdempotencyRecord 强制 project_id，不能用虚构项目解决首次创建。S61B 在独立迁移中增加
最小组织级初始化幂等记录和稳定项目身份唯一约束；先授权、校验、配额，再幂等 Claim 和事务写入。
事务中复核配额；唯一约束处理同键、不同幂等键的并发创建，失败必须回滚；冲突不泄露不可见项目。
该迁移必须含 PostgreSQL/Standalone Upgrade、Downgrade/恢复和 Transfer 测试。S61A 无数据库
变更，不提前创建空表；详细字段及迁移评审在 S61B 提交前补入本 ADR。

## 兼容与验证

旧 38 个工具和各领域 Schema 保留，连接协议为 `s61-mcp-connection-v1`，tools/list 精确排序。
新只读工具如实声明 readOnlyHint/idempotentHint，注解不替代服务端授权。
覆盖机器账号有效/过期/撤销/禁用、组织禁用、用户 JWT 拒绝、Scope 恢复指引、真实 SDK HTTP
逐请求身份隔离、stdio 进程身份、配置无令牌与错误脱敏。HTTP Cookie 失效不影响合法机器账号。

Codex 配置字段依据 [官方 MCP 配置文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：
stdio 使用 command/args/env_vars；HTTP 使用 url/bearer_token_env_var。不声称模板已安装。
