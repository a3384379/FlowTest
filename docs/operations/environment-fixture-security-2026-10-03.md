# 环境夹具与运行时安全更新（2026-10-03）

## 问题与修改范围

固定的 Nginx 环境夹具包含 PCRE2 10.48，现有 High / Critical 门禁报告可修复的 CVE-2026-103111。官方最新 Alpine 与 Debian 镜像的实际依赖仍未消除当前扫描阻塞。

将环境实验室默认示例、前后端测试、S26 验收脚本、Compose 允许列表及安全扫描统一更新为以下多架构不可变镜像：

```text
cgr.dev/chainguard/nginx@sha256:a104d1995e56b7a15e8f152078dfbdb1ecbf9f9d1af311e7906e7b4c0c790cf2
```

该镜像可匿名拉取，amd64 与 arm64 均包含 PCRE2 10.49-r1，使用 UID / GID 65532，默认监听 8080。[供应方兼容说明](https://images.chainguard.dev/directory/image/nginx/overview)列出非 root 用户、端口及只读根文件系统所需的 `/run`、`/var/lib/nginx/tmp`，与现有环境执行器的固定安全参数一致。

同时纳入本次门禁已定位的依赖修复：urllib3 2.8.0、Axios 1.20.0 / follow-redirects 1.16.1；Python 与 Mock 镜像在选择基础镜像后安装已修复的 Debian OpenSSL / PCRE2；前端镜像要求 Alpine PCRE2 至少 10.49-r0；环境 daemon 要求 PCRE2 至少 10.49-r0、Expat 至少 2.8.5-r0。Python、Node、pnpm、Go 与测试框架版本维持原样。

## 已执行验证

- 使用注册表返回的多架构摘要、子清单和各层 SHA-256 校验下载结果，检查两个架构的实际镜像配置与包数据库。
- 对两个架构的原始 OCI 镜像执行 Grype 0.116.1，沿用 `.grype.yaml`、`--only-fixed --fail-on high`：High / Critical 均为 0。扫描对象未加入诊断工具。
- 原始 arm64 镜像的临时诊断构建仅增加 BusyBox 及其加载器，在 UID / GID 65532 下验证 Nginx 配置及 HTTP 根路径：200。该构建未用于安全扫描，也不作为只读容器或完整 S26 验收的证明。
- `make test-backend-targeted`：环境实验室、CI 计划与 Required Gate 的 131 项测试通过；`make test-frontend-targeted`：环境页面 3 项测试通过。
- 受影响 Python 文件的 Ruff 格式与规则、前端文件的 Prettier / ESLint、全部工作流 YAML 解析及六处夹具引用一致性检查通过。
- `pnpm --dir frontend build` 通过；`pip-audit` 无已知漏洞，`pnpm audit --audit-level high` 通过。后者保留测试框架已有的两个 moderate 报告，不在本次改动中升级工具链。

## 合并与验收边界

两处 CI 工作流仅修改镜像引用，不调整检查矩阵、漏洞阈值、忽略规则或正式状态发布器。该改动属于治理文件变更，必须按[受控 Bootstrap 流程](../development-efficiency-phase3.md#验证性能与激活)核对最新 Head 的完整远程检查及 Review Thread，再实施普通合并并恢复原门禁配置。具体远程运行与合并证据记录在对应 PR。

既有签名模板和项目允许列表不自动迁移；部署方仍需明确允许所选镜像。未执行生产部署、生产数据库迁移、Compact 容量 RC、真实外部服务或发布签字。本机普通 Docker 容器启动停留在 Created，已清理本次临时容器；完整的只读安全参数、Seed、重启后清理以 Bootstrap 的真实 Compose / S26 验收为准。原工作区及七个原有健康服务保持不变。
