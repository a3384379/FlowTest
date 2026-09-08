# MCP 首次连接与故障恢复（S61A/S61B）

## 首次人类授权

由有权限的用户在现有组织服务账号管理入口签发机器账号，明确组织、Scope、有效期与授权任务范围。
令牌只在签发/轮换时交付一次，存入用户控制的安全环境变量或凭据管理工具；不要粘贴到模型对话、
URL、命令参数、日志或仓库。轮换、撤销和过期继续使用现有 ServiceAccountService。
连接命令不自动签发、读取浏览器会话或修改权限。零项目初始化仅在账号被明确授予
`mcp:project:bootstrap` 时可用，连接诊断不会静默授予该 Scope。

## 显式生成配置

安装仓库 backend 包提供的 `flowtest-mcp` 命令后，用户可显式运行：

```sh
flowtest-mcp setup --api-base-url http://localhost:8000 --token-env-var FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN
flowtest-mcp setup --transport streamable-http --api-base-url http://localhost:8000 --mcp-url http://localhost:8765/mcp
```

只输出诊断和 `config_template`；不会读取或写入用户 Codex 配置。用户确认后自行将模板加入 MCP
配置。stdio 用 env_vars 传递指定环境变量；HTTP 用 bearer_token_env_var，由宿主为每次请求提供
机器身份。运行 HTTP Adapter 的进程不使用共享账号代替客户端身份。远程部署必须使用受信任的
HTTPS 和正常网络控制，不因连接失败关闭 TLS/SSRF 校验。删除了不安全的 `--token` 明文参数。

setup 验证的是 **应用网关机器认证**，不测试模板地址的 MCP 握手；输出始终明确
`transport_verified=false`，不能据此报告真实 LLM/Skill 已通过。随后在宿主发现实际工具，调用
`flowtest.inspect_connection`，传 `{"request":{}}`，再调用已有授权读取工具确认宿主连接。
setup 成功不授予新 Scope，不批准 Review/Apply/Publish/Preview。初始化工具默认 Dry Run；
真实创建项目、Test/Sandbox 环境或 Service Target 需要固定组织、该 Scope 和幂等键，且不会
修改已有成员、凭据、TLS 或出站策略。

| 诊断 | 处理 |
| --- | --- |
| AUTH_REQUIRED | 检查指定机器配置；由用户在现有授权入口签发/配置，不猜测密码 |
| AUTH_EXPIRED | 通过现有授权入口轮换/续接账号，再更新安全配置 |
| SCOPE_REQUIRED / next_action=request_scope | 核对本任务所需最小 Scope，请用户明确授权；不切换管理员身份 |
| SERVER_UNREACHABLE | 检查用户指定服务地址和部署状态；不回退内部 SQL 或其他接口 |
| CONTRACT_VERSION_UNSUPPORTED | 更新兼容 Adapter；保留旧领域契约，不伪造工具 |
| FEATURE_DISABLED | 请求确认相应 Feature，不自行更改开关 |
| TOOL_UNAVAILABLE | 宿主未暴露该工具；不等同于缺凭据，不以 shell 变量缺失判断已有 MCP 会话 |

正式生成阶段只经 MCP。API 网关是 Adapter 内部实现；不允许模型使用通用 REST/curl 或浏览器
登录补缺失权限。Fixture/ASGI 测试与真实宿主验收分别记录，未执行实测不得填 PASS。

配置字段来源：[Codex 官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。
