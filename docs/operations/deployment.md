# FlowTest V2.0 单机部署手册

## 前置条件

- ARM64 或 x86_64 Docker Desktop / Docker Engine，Compose v2。
- 建议至少 4 CPU、8 GB 内存和 20 GB 可用磁盘；容量应按附件保留期额外规划。
- 可解析的业务域名、TLS 证书和仅管理员可读的生产 `.env`。

## 首次部署

1. 复制 `.env.example` 为 `.env`。
2. 将 `FLOWTEST_ENVIRONMENT` 设置为 `production`。
3. 替换 JWT 签名密钥、管理员密码、AES-256-GCM 密钥、PostgreSQL、MinIO 凭据并设置
   `FLOWTEST_SECURE_COOKIES=true`。启用 OIDC、Vault、Grafana 或 PITR 时，同时替换相应 Client
   Secret、Vault Token、Grafana 密码和 WAL-G 加密密钥。应用会拒绝核心服务携带示例凭据的生产配置。
   启用 AI 时还必须配置 HTTPS OpenAI-compatible 网关、模型和运行时 API Key；AI 默认关闭。
4. 运行 `docker compose config --quiet`，确认插值结果中没有空凭据。
5. 运行 `docker compose up -d --build --wait`。
6. 验证 `/api/v1/live`、`/api/v1/ready`、`/api/v1/metrics` 和 Web 首页。
7. 使用初始管理员登录并立即修改密码。

## TLS 接入

`deploy/nginx/tls.conf.template` 是外层 Nginx 模板。将证书只读挂载到
`/etc/nginx/tls/tls.crt` 和 `/etc/nginx/tls/tls.key`，用实际域名替换
`${FLOWTEST_SERVER_NAME}`。模板包含 WebSocket 代理、50 MB 上传上限、HSTS 和 TLS 1.2/1.3。

## 资源与扩容

Compose 已为数据库、缓存、对象存储、API、Worker、Beat 和 Web 设置 CPU/内存上限。
`FLOWTEST_WORKER_CONCURRENCY` 默认 4；Data 与 AI 使用独立 Worker/队列。调整后应重新运行容量门槛。V2.0 正式部署仍为单机 Compose，不支持跨主机调度或 Kubernetes。

## 启停

```bash
docker compose up -d --wait
docker compose ps
docker compose logs --tail=200 backend worker worker-data worker-ai beat
docker compose stop
```

不要使用 `docker compose down --volumes` 停止生产环境；该命令会删除持久卷。
