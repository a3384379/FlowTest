# FlowTest V1.0 威胁模型

## 资产与信任边界

- 资产：用户凭据、JWT/Refresh Token、项目 Secret、CI Token、Webhook Secret、API 请求响应、
  Workflow Snapshot、Runner 注册/身份 Token、Lease/Fence/Event、报告、附件和审计记录。
- 外部边界：浏览器到 Nginx/API、远程 Runner 到 HTTPS Control Plane、Worker 到目标 API、通知
  Webhook、导入文档和文件上传。
- 内部边界：API/Worker/Beat 到 PostgreSQL、Redis、MinIO；Runner 容器到目标网络；备份目录到
  恢复环境。

## 主要威胁与控制

| 威胁 | 控制 |
|---|---|
| 密码与 Token 被窃取 | Argon2id、短期 Access Token、Refresh 轮换/撤销、HttpOnly/SameSite、生产强制 Secure Cookie |
| 越权与跨项目访问 | 固定四级能力矩阵、服务层统一授权、项目隔离与拒绝测试 |
| Secret/Token 泄漏 | AES-256-GCM、只写接口、运行内存与持久化边界分离、复合字段与 Extract 输出脱敏 |
| SSRF / DNS 重绑定 | 域名白名单、私网 CIDR 双重授权、解析后逐地址校验、元数据/回环/链路本地永久拒绝 |
| 恶意导入与文件 | 文档解析限制、50 MB 上限、对象 key 服务端生成、Manifest 文件名编码与哈希校验 |
| 重放、重复执行与洪泛 | Idempotency-Key、Webhook 时间窗/HMAC、Redis 分桶限流、CI Token scope |
| 伪造 Runner 或窃取 Worker 身份 | 管理员一次性限时注册令牌、48 字节高熵 Token、SHA-256 查找哈希、明文只返回一次、生产 HTTPS、每 Token 单身份、Drain/停用审计 |
| 旧 Worker 重放结果或重复终态 | PostgreSQL Lease、原子递增 Fence、Runner/Lease/Task/Fence 四重校验、节点唯一约束、有界重试 |
| 恶意计划越权或 Runner 宿主逃逸 | 只恢复平台加密 Snapshot 并校验 SHA-256、Host/CIDR SSRF 策略、无用户 Compose/Shell/Plugin、非 root/只读/Drop ALL/seccomp、不挂 Docker Socket 或 ServiceAccount Token |
| Runner 控制面洪泛 | 按哈希 Token 身份的独立高吞吐限流桶、有界结果、并发上限、低基数指标与 429/5xx 告警 |
| 工作流历史篡改 | 不可变 Version/Snapshot、审计 Trace ID、发布前 DAG/配置校验 |
| 供应链与镜像漏洞 | uv/pnpm 锁、依赖审计、Ruff 安全规则、Action SHA 固定、Grype 高危/严重扫描 |
| 备份篡改或恢复失败 | PostgreSQL custom dump、MinIO SHA-256 Manifest、隔离卷自动恢复验证 |

临时扫描例外必须记录在 [漏洞例外台账](vulnerability-exceptions.md)，包含范围、原因、补偿控制、
责任人与到期日；Critical 漏洞不得例外。

## 残余风险

- V1.0 是单机 Compose，宿主机故障仍依赖外部备份系统与恢复时间目标。
- Redis 限流故障采用告警并放行，需由边缘网关提供第二层限流。
- TLS 私钥、数据加密密钥和备份介质由部署方管理，不存入仓库。
- 目标 API 的业务副作用无法由平台自动回滚，测试环境应使用隔离账户和可清理数据。
- Runner Token 窃取后在停用前仍可认领符合 Profile 的已验证计划；部署方必须将 Token 放入
  Secret Store，限制 Runner 网络出站，并对异常心跳、地址和并发量告警。
- PostgreSQL 是 Lease/Fence 一致性单点；数据库不可用时 Runner 不能安全继续认领，高可用性需由
  部署方的 PostgreSQL 方案和经验证恢复流程提供。
