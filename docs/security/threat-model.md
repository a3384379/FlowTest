# FlowTest V1.0 威胁模型

## 资产与信任边界

- 资产：用户凭据、JWT/Refresh Token、项目 Secret、CI Token、Webhook Secret、API 请求响应、
  Workflow Snapshot、报告、附件和审计记录。
- 外部边界：浏览器到 Nginx/API、Worker 到目标 API、通知 Webhook、导入文档和文件上传。
- 内部边界：API/Worker/Beat 到 PostgreSQL、Redis、MinIO；备份目录到恢复环境。

## 主要威胁与控制

| 威胁 | 控制 |
|---|---|
| 密码与 Token 被窃取 | Argon2id、短期 Access Token、Refresh 轮换/撤销、HttpOnly/SameSite、生产强制 Secure Cookie |
| 越权与跨项目访问 | 固定四级能力矩阵、服务层统一授权、项目隔离与拒绝测试 |
| Secret/Token 泄漏 | AES-256-GCM、只写接口、运行内存与持久化边界分离、复合字段与 Extract 输出脱敏 |
| SSRF / DNS 重绑定 | 域名白名单、私网 CIDR 双重授权、解析后逐地址校验、元数据/回环/链路本地永久拒绝 |
| 恶意导入与文件 | 文档解析限制、50 MB 上限、对象 key 服务端生成、Manifest 文件名编码与哈希校验 |
| 重放、重复执行与洪泛 | Idempotency-Key、Webhook 时间窗/HMAC、Redis 分桶限流、CI Token scope |
| 工作流历史篡改 | 不可变 Version/Snapshot、审计 Trace ID、发布前 DAG/配置校验 |
| 供应链与镜像漏洞 | uv/pnpm 锁、依赖审计、Ruff 安全规则、Action SHA 固定、Docker Scout 高危/严重扫描 |
| 备份篡改或恢复失败 | PostgreSQL custom dump、MinIO SHA-256 Manifest、隔离卷自动恢复验证 |

## 残余风险

- V1.0 是单机 Compose，宿主机故障仍依赖外部备份系统与恢复时间目标。
- Redis 限流故障采用告警并放行，需由边缘网关提供第二层限流。
- TLS 私钥、数据加密密钥和备份介质由部署方管理，不存入仓库。
- 目标 API 的业务副作用无法由平台自动回滚，测试环境应使用隔离账户和可清理数据。
