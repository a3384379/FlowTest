# ADR 0021：声明式性能场景与隔离 k6 Runner

## 状态

已接受，S25 实施。

## 背景

V3 需要把性能结果纳入基线和发布门禁，但允许用户上传 k6 JavaScript 会重新引入任意脚本执行、
容器逃逸、Secret 泄漏和不可重放等风险。性能负载还会与普通 API/Workflow Worker 争抢 CPU、内存和
队列资源，因此不能直接复用 General Worker。

## 决策

1. 用户只提交版本化的 `PerformanceScenarioDefinition`。首版目标限定为单个 REST 请求或纯 HTTP
   Workflow，负载模型限定为 `constant-vus` 和 `ramping-vus`；平台不接收 JavaScript 字段。
2. `K6ScenarioCompiler` 把经过 Pydantic 校验的结构化数据确定性编译为平台固定程序。所有字符串均经
   JSON 编码，HTTP 重定向关闭，响应体默认丢弃；编译后保存 SHA-256，发布版本不可修改。
3. `PerformanceRun` 在入队时固定定义、场景版本和编译哈希。Runner 执行前重新编译并比对哈希，
   同时重新执行项目级 SSRF/DNS/CIDR 校验，阻止 Snapshot 漂移和目标策略绕过。
   S25 不接受敏感 Header、敏感 Query 参数、Secret 形态值或敏感 Body 字段；认证性能场景须待
   Credential Broker 接入后开放，Secret 不进入场景、编译产物和原始指标。
4. 性能任务只进入 Celery `performance` 队列。Compose 使用独立的 `performance-runtime` 镜像，固定
   `grafana/k6:2.2.0` 多架构 digest，以非 root 用户、只读根文件系统、`cap-drop ALL`、
   `no-new-privileges` 和受限 `/tmp` 运行。
5. k6 原始 NDJSON 指标保存到 MinIO，数据库仅保存 Artifact 元数据、聚合指标、阈值证据和标准错误；
   单个原始指标产物上限 50 MB。上一条同场景成功运行自动成为回归基线。
6. 性能阈值与既有 `QualityGate` 同时计算。阈值失败使 Performance Run 失败；门禁额外记录 P95 基线
   回归证据，但不改写不可变的原始运行事实。

## 结果

- 平台可以复用 k6 的 Scenario 与 Threshold 执行语义，同时不开放用户脚本。
- 性能负载、普通功能执行和 AI/Data 任务具有独立故障域和容量配置。
- 更新 k6 版本会改变编译/运行基线，必须经过固定 digest 更新、全量回归和基线审阅。
- S25 不支持浏览器性能、任意 k6 扩展、用户 JavaScript 或含非 HTTP 节点的 Workflow。
