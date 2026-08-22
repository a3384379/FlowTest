# ADR 0031：Windows 云桌面的 Standalone 无 Docker 运行时

## 状态

已接受，进入 S37；Windows x64 云桌面实机验收待执行。

## 背景

公司云桌面可能只有 Windows 10、低配 CPU，且不提供 SLAT、嵌套虚拟化、WSL2 或 Docker Desktop。
Compact Docker 仍需要六个容器和 PostgreSQL/Redis/MinIO，因此不能在这类桌面上安装。需求是让开发人员
在个人电脑修改代码、将经过校验的包复制到公司桌面执行功能测试，不要求公司端修改代码或安装容器平台。

## 决策

新增显式 `standalone` 运行档位：

- SQLite 文件数据库启用 WAL、外键和忙等待；首次启动从现有 SQLAlchemy 模型建立当前基线，并记录
  `20260822_0034` Alembic revision。后续结构变化仍须通过 Alembic 维护。
- `LocalObjectStorage` 将 Artifact 写入 `data/artifacts`，使用相对键校验、临时文件替换和内容类型旁车文件。
- `InProcessExecutionEventBus` 保留有界事件历史并向同一进程内 WebSocket 订阅者广播。
- `InProcessRateLimiter` 和 `StandaloneTaskDispatcher` 替代 Redis/Celery；工作流、测试计划和可选 AI
  在 API 事件循环的有界并发槽中执行，定时任务由同一进程调度器轮询。
- Performance Lab、Environment Lab、Runner Fabric 固定关闭；Full/Compact 的外部目标协议能力不因此
  获得宿主级执行权限。
- FastAPI 在配置了前端 dist 时服务静态 Web；PowerShell 脚本负责首次密钥生成、启动、停止、验收和
  SQLite/附件备份。发布包可携带 Python 3.13 运行时和 wheels，以避免公司桌面安装开发工具。

## 不采用的方案

- 不修改 Compact 的 Compose，使其偷偷使用 SQLite 或本地文件；这会破坏 Full↔Compact 数据与运维契约。
- 不在公司桌面安装 Docker Desktop、WSL2 或虚拟机；硬件虚拟化缺失时无法可靠运行。
- 不把未完成任务伪装成可恢复队列；Standalone 重启时进程内任务会终止，持久化状态由业务服务保留并由
  后续版本提供明确恢复策略。

## 后续约束

Standalone 适合单用户/低并发功能测试，不提供 HA、跨进程锁、性能容量或崩溃后任务续跑保证。需要这些
能力时必须切换 Compact 或 Full。任何数据迁移、升级和恢复操作必须先备份 `data`，并把
`FLOWTEST_DATA_ENCRYPTION_KEY` 与业务备份分开保管。
