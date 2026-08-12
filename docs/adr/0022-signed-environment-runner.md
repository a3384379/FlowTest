# ADR 0022：签名环境模板与隔离 Provision Runner

## 状态

已接受，S26 实现。

## 背景

测试流程需要可重复的短时依赖环境，但允许用户上传 Compose、容器命令、脚本、Secret 或卷挂载，
等同于把宿主级执行能力开放给不可信输入。环境创建还必须在失败、超时、取消、TTL 到期和 Runner
重启后可靠回收，不能仅依赖正常完成路径。

## 决策

1. Environment Template 是管理员拥有的声明式契约，只包含固定 Digest 镜像、服务拓扑、受限环境变量、
   HTTP/TCP 健康检查、资源上限、TTL 和平台内置 Seed Profile。Pydantic 契约使用 `extra=forbid`，不提供
   Compose、command、entrypoint、script、Secret、privileged、device 或 volume 字段。
2. 每个版本保存规范 JSON、SHA-256 和平台 HMAC-SHA256-v1 签名。签名密钥从部署数据加密密钥经独立
   域分隔材料派生；Provision 和 Runner 执行前均重新计算哈希并使用常量时间比较验证签名。
3. 模板注册、创建版本和停用只允许系统管理员。镜像必须同时匹配 OCI Digest 语法和部署级精确白名单；
   普通项目成员只能选择仍启用的已签名版本。
4. Provision 只进入 Celery `environment` 队列。Environment Worker 以 UID/GID 65532、只读根文件系统、
   Drop ALL 和 `no-new-privileges` 运行，不挂载宿主 Docker Socket，只能访问独立 DinD daemon 的内部
   Control Network。
5. Runner 把签名类型契约翻译为固定 Docker CLI 参数：独立 bridge、固定名称和 Label、Digest 拉取、
   非 root UID/GID、只读根文件系统、Drop ALL、`no-new-privileges`、CPU/内存/PID 上限、只读镜像默认
   Entrypoint，以及随机宿主端口。所有调用使用参数数组，不经过 Shell，也不接受用户命令。
6. DinD daemon 不发布宿主端口，只接入内部 Control Network 和独立 Egress Network。基础镜像固定为
   Docker 29.7.2 多架构 Digest；containerd 固定在 v2.3.3 commit，并只升级已有安全修复的 gRPC/x/text
   依赖。未使用的 Compose/Buildx 插件从最终 daemon 镜像移除。
7. 实例保存模板 Snapshot、签名、Fencing Token、端点、Seed 证据、TTL 和独立 Cleanup 状态。
   Idempotency-Key 防止重复 Provision；Fencing Token 阻止旧投递覆盖新状态。
8. Provision 无论成功或失败都先清理同实例旧 Label 资源。取消和 TTL 只提交同一个幂等 Cleanup；
   Cleanup 按 Label 枚举容器、网络和卷，容器删除带 `--volumes`。失败保留稳定错误码并由 Beat
   Reconciler 重试，Runner 重启或消息重投不会重复创建或漏删资源。

## 结果

- 平台可以创建可复现环境，而不开放任意容器编排能力。
- 独立 daemon 仍是高权限基础设施，因此必须保持不可从宿主访问、固定供应链输入，并与 Runner 和
  白名单 fixture 一起执行 `only-fixed` High/Critical 镜像扫描。
- S26 不提供跨主机调度、Kubernetes、用户自定义 Seed 或 Secret 注入；这些能力必须在后续 Runner
  Fabric 中重新评估信任边界。
