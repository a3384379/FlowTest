# ADR 0027：不可变镜像与离线分发

状态：Accepted
日期：2026-08-19

## 背景

公司测试环境经常不允许访问 Docker Hub、GHCR、npm 或 Python 下载站。若 Compact 只支持
在目标机执行 `docker compose up --build`，即使运行拓扑已缩减，仍无法通过多数企业的
出站网络和供应链审批。仅使用 Tag 又会使管理员无法证明审批、测试和部署的是同一个镜像。

## 决策

1. Compact 基础 Compose 只声明明确镜像，不包含构建语义；源码工作站通过独立
   `compose.build.yaml` 构建 Backend 和 Frontend。Backend 与合并 Worker 必须复用同一镜像。
2. PostgreSQL、Redis、MinIO、Backend 和 Frontend 是 Compact 的 5 个唯一镜像。部署可通过
   `images.env` 替换全部引用，密钥 `.env` 与镜像配置分离。
3. 私有仓库发布器会推送全部 5 个镜像，并从仓库返回值生成
   `repository@sha256:...` 形式的 `images.env`。发布 Tag 带有 `amd64` 或 `arm64` 后缀，
   每个架构分别发布；正式环境不以可变 Tag 作为部署证据。
4. 离线包按 `linux/amd64` 或 `linux/arm64` 单架构生成，包含镜像 Tar、镜像 ID/平台清单、
   包内逐文件 SHA-256、外部压缩包 SHA-256 和必要运维脚本，不包含密码或业务数据。
5. 离线安装在加载后再比对每个镜像 ID 和架构，且只允许
   `--pull never --no-build` 启动。外部摘要必须通过与离线包分离的受信发布渠道传递。
6. 无外网升级必须先导入和校验新镜像，再生成 PostgreSQL + MinIO 一致性备份，最后启动
   新镜像并执行同一 Alembic 链。回滚时必须同时恢复旧镜像与升级前数据。

## 结果

目标机只需 Docker Engine/Desktop、Compose v2、OpenSSL、Curl 和足够磁盘，不需要源码、
Git、Python、Node.js 或外网。离线包不是密钥和业务备份；部署后仍必须独立保管 `.env`、
`FLOWTEST_DATA_ENCRYPTION_KEY` 以及数据备份。SHA-256 只能检测内容变化，不能单独证明发布者身份；
正式发布后续仍应接入公司的签名和制品审批链。
