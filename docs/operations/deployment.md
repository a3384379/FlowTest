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
   启用 V3 Environment Lab 时，将 `FLOWTEST_FEATURE_ENVIRONMENT_LAB_ENABLED=true`，并把管理员审核过的
   `repository@sha256:...` 精确列表写入 `FLOWTEST_ENVIRONMENT_IMAGE_ALLOWLIST`；空白名单或非 Digest
   条目会阻止应用启动。不要加入包含 Shell、调试工具、特权 Entrypoint 或不受维护的镜像。
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
`FLOWTEST_WORKER_CONCURRENCY` 默认 4；Data、AI、Performance 与 Environment 使用独立 Worker/队列。
`FLOWTEST_PERFORMANCE_WORKER_CONCURRENCY` 默认 1，单场景 VU 和持续时间分别受
`FLOWTEST_PERFORMANCE_MAX_VUS`、`FLOWTEST_PERFORMANCE_MAX_DURATION_SECONDS` 限制。Performance
Worker 以非 root、只读文件系统运行固定 k6，不应挂载 Docker Socket。调整后应重新运行容量门槛。
Environment Worker 同样以非 root、只读和 Drop ALL 运行，不挂载宿主 Docker Socket；它只通过内部
Control Network 连接独立 `environment-docker` daemon。daemon 因 DinD 需要特权模式，但不得发布宿主
端口、加入业务数据库网络或复用宿主 Docker daemon。模板 TTL 同时受模板值和
`FLOWTEST_ENVIRONMENT_MAX_TTL_SECONDS` 限制；Provision、Cleanup、Health 和 Reconcile 超时分别由
对应 `FLOWTEST_ENVIRONMENT_*` 配置约束。修改镜像白名单、daemon 网络或这些上限后，应重新执行 S26
真实 Compose 冒烟、Playwright 和三类环境镜像扫描。
V2.0 正式部署仍为单机 Compose，不支持跨主机调度或 Kubernetes。

## 启停

```bash
docker compose up -d --wait
docker compose ps
docker compose logs --tail=200 backend worker worker-data worker-ai worker-performance worker-environment environment-docker beat
docker compose stop
```

停止或升级 Environment Worker 前，先在环境实验室确认没有 `queued`、`provisioning` 或 `cleaning` 实例；
如果进程意外中断，恢复 Worker 和 Beat 后由 Fencing Token 与 Reconciler 继续 Provision 或提交幂等 Cleanup。
不要手工删除带 `flowtest.environment.*` Label 的单个容器或网络，以免数据库状态和实际资源短暂不一致。

不要使用 `docker compose down --volumes` 停止生产环境；该命令会删除持久卷。
