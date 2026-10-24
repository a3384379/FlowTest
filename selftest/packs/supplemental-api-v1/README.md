# 原生 API P0 补充包

本包保留既有 `native-api-v1` 12 项和 `extended-v1` 19 项的原文件及摘要，另冻结 15 个原生变体。每项均由 A 安装并发布 Workflow、Case、Suite，再通过 Plan → Run 执行，业务请求由原生引擎发送到临时 B 或受控 Mock。

`coverage.json` 列出逐场景验收 ID；`exclusions.json` 记录当前部署配置不能在 600 秒预算内真实构造的登录 JWT 过期变体。非法令牌不能替代过期令牌，不能据此宣称 ST-API-001 全部通过。加载器将覆盖及排除文件与核心文件摘要共同冻结到包摘要。

会话 Cookie、JWT 和随机密码只用于原生请求及已授权的内存采证。持久证据仅保留独立状态、错误码、固定 trace、断言值摘要以及合成 Mock 请求的既有白名单字段。省略 `value` 与显式 `null` 必须依据原始请求体的字段存在性区分。

补充身份、组织和 B 上已归档版本由本隔离目标的整体精确销毁负责回收。首次核验只能产生 `OWNED_ASSET_DISPOSAL_PENDING`；专用 finalizer 必须核验拥有关系、固定目标容器/卷/镜像及 Docker 实际不存在后才完成，保留原始执行状态及销毁前证据。

本地双 ASGI 测试与部署验收分开记录。部署前不得把单元或 ASGI 通过写成 Full、Compact 或 Standalone 验收通过。
