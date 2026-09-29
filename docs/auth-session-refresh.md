# 登录会话续期与失效处理

## 现有流程

平台访问令牌保持短期有效（默认 15 分钟），只保存在当前页面内存中。刷新令牌保存在 `flowtest_refresh` HttpOnly Cookie；服务端只保存其摘要。登录与刷新响应继续返回 `access_token` 和 `expires_in`。页面用响应 TTL 计算提前续期窗口：`min(60 秒, TTL 的 10%)`。

业务请求在发送前检查期限。接近到期时，同一页面的请求共用一次刷新；刷新得到的候选访问令牌先调用 `/auth/me` 核对用户，再一次性更新页面身份与期限。如果刷新成功但 `/auth/me` 暂时失败，页面暂存候选令牌并在恢复时先重试身份确认。服务端在业务处理之前拒绝已过期访问令牌时，返回 `401 / ACCESS_TOKEN_EXPIRED`，请求层可刷新并重放原请求一次。只有可重放的请求体（无请求体或已序列化字符串）进入这条路径；网络超时、503、普通 403 和被测接口返回的 401 均不会触发业务重放。

## 错误和页面状态

| 错误或状态 | 处理 |
| --- | --- |
| `ACCESS_TOKEN_EXPIRED` | 静默续期，原请求最多重试一次 |
| `INVALID_REFRESH_TOKEN` | 确认会话失效，转登录页并提示一次 |
| `REFRESH_ROTATION_CONFLICT` | 等待 250 毫秒后，最多再尝试一次刷新；不返回凭证 |
| `INVALID_ACCESS_TOKEN` | 不视为正常过期，要求重新认证 |
| `CSRF_VALIDATION_FAILED` | 拒绝不可信来源，不自动续期 |
| 网络故障、限流、服务暂不可用 | 保留本地编辑上下文；操作失败后可重试恢复 |

后端错误仍采用 `{ "error": { "code", "message", "details", "trace_id" } }`。登录与刷新响应设置 `Cache-Control: no-store`。首次改密成功后撤销该用户的所有刷新会话，页面要求用新密码重新登录。

## 并发与安全边界

服务端先以数据库写操作串行化同一用户的刷新、注销和改密，再通过条件更新消费旧刷新会话，并在同一事务创建后继。两个事务不能从同一旧令牌得到两个后继；提交失败时旧会话仍可用。注销使用刷新 Cookie，无 Cookie 时幂等返回 204；若请求携带已轮换的旧 Cookie，则沿 `replaced_by_id` 撤销当前链后继。链损坏或超出遍历上限时返回错误，不报告成功。

浏览器在安全上下文且支持 Web Locks 时，串行化登录、刷新、注销和改密。BroadcastChannel 仅发送不含令牌的状态事件。其他环境依赖服务端原子消费和一次有限冲突恢复；极端竞争或刷新响应丢失后可能需要重新登录。平台令牌不会进入 localStorage、草稿、广播或被测接口请求。

浏览器 Cookie 写接口校验精确 Origin。无 Origin 的刷新与注销请求须发送 `X-Requested-With: FlowTest`；JSON 登录请求可凭 `application/json` 触发浏览器预检。`Origin: null` 和不允许的来源会被拒绝。前端独立认证客户端发送此头，不附加旧组织头；OIDC 回调维持原有 state/nonce 验证。Cookie 名、Path、HttpOnly、SameSite 与 Secure 配置未变；自定义 API 前缀下设置和删除 Path 一致。

请求记录用户、会话代次和组织上下文。身份或组织变化后，迟到的业务响应不能进入新身份的查询结果；实际应用在会话代次变化时同步清空 React Query 缓存。草稿存储键沿用用户和项目边界；`DraftSessionProvider` 在同一用户重新登录期间保留内存会话，新用户使用新 Provider。无法持久化的输入仍应按界面警告先保存，不能承诺浏览器关闭后恢复。

刷新会话撤销不会立即吊销已经签发的访问 JWT。旧 JWT 在有效期内仍可能被接受；本轮也未新增服务端绝对会话期限、真实空闲期限或完整令牌家族检测。数据库表结构未改动，不需要迁移。

## 验证与部署

本地开发先运行具名认证测试：

```bash
make test-backend-targeted TARGETS='["tests/test_auth_session_refresh.py","tests/test_access_api.py","tests/test_oidc.py"]'
make test-frontend-targeted TARGETS='["src/lib/api.test.ts","src/features/auth/auth-session.test.ts","src/App.test.tsx"]'
```

合并门禁和发布验收分别核查最新提交。部署时先更新兼容新错误码和原子轮换的后端，再更新前端静态资源。隔离环境应使用合法短 TTL 经过两个访问令牌周期，验证保存只执行一次、双标签页、断网恢复、过期后注销、OIDC、PostgreSQL 与 Standalone SQLite。回滚前端可能重新出现到期中断；不能以关闭鉴权、延长为永久令牌或回退原子轮换作为补救。
