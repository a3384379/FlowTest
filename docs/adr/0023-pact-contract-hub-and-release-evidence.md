# ADR 0023：Pact 契约中心与发布兼容证据

## 状态

已接受，S27 实现。

## 背景

OpenAPI 能描述 Provider 接口并识别 Schema 破坏，但不能单独表达每个 Consumer 已实际依赖的
交互。发布判断需要同时回答“Provider 文档是否破坏”和“已知 Consumer 契约是否通过”，
并且必须保留可审计证据。Pact 文档、Broker 内容和 Provider 地址都属于不可信输入。

## 决策

1. 服务目录、Pact 版本、Provider Verification 和 Deployment Compatibility Check 使用
   PostgreSQL 作为事实源。Pact 以规范 JSON 和 SHA-256 去重，导入后不修改原版本。
2. S27 只支持 HTTP Exact Matcher。领域解析器使用限定类型和结构上限，拒绝 Message Pact、
   Matching Rule、Generator、Plugin、认证/Cookie/Secret 字段和过深或过大的文档。
3. Provider 目标必须是无凭据、Query、Fragment 和 Path 的 HTTP/HTTPS Origin。验证器禁止
   Redirect 和系统代理，每次交互前重新执行项目出站/DNS/CIDR 策略；响应、超时和错误码有固定上限。
4. Provider State 只能调用同一 Origin 下固定的 `/_pact/provider-states`，不接受 Pact 自定义 URL
   或脚本。验证证据按 Pact 版本和 Provider 版本保留，旧失败不会被其他版本的成功覆盖。
5. 可选 Pact Broker 由部署端固定 Origin 和 Token；用户只提供 Consumer、Provider 和版本坐标。
   路径分段编码后请求，Token 不进入数据库、日志或 API 响应。
6. Deployment Check 只基于指定 Provider 版本的最新 Pact 验证与已绑定 OpenAPI 运行判断。
   存在失败验证或 OpenAPI Breaking Change 时为 `unsafe`，证据缺失时为 `unknown`，
   全部证据通过时才为 `safe`；每次判断都持久化。

## 结果

- OpenAPI 和 Pact 以统一服务目录、依赖图和兼容矩阵展示，发布判断不依赖瞬时 UI 状态。
- Exact Matcher 不覆盖 Pact V4 的高级 Matching Rule、Message Pact 或 Broker 发布流程；需要这些能力时
  必须新增受控 Runner 和独立安全评估，不直接执行用户插件或脚本。
