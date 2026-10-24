# Full / Compact 原生链隔离验收

此入口复用已冻结的 candidate / fixture 镜像，不构建产品镜像，不连接日常项目。
它验证原生 Workflow → Case → Suite → Plan → Run、独立 Observer 和部署隔离。
它不代表完整 Full 发布环境、真实模型宿主或性能实验室已经验收。

## 前提

- 在仓库根目录运行，使用现有 `backend/.venv/bin/python`。
- 提供已经通过身份校验的独立 Standalone 自测栈目录。
- Docker 本地已有 `postgres:17.6-alpine`、`redis:8.2.1-alpine` 和
  `minio/minio:RELEASE.2025-07-23T15-54-02Z`。启动时冻结其实际 image ID。
- Full 与 Compact 串行运行，先检查 Docker 内存与其他自测任务。
- 每次提供全新目录；未知启动结果不能换 nonce 冒充重试。

## 拓扑

| 资源                     | Full                                     | Compact                    |
| ------------------------ | ---------------------------------------- | -------------------------- |
| A / B API                | 独立两个实例                             | 独立两个实例               |
| PostgreSQL、Redis、MinIO | A / B 各一组，独立卷和网络               | A / B 各一组，独立卷和网络 |
| Worker                   | 每个实例独立 general / data worker       | 每个实例一个合并 worker    |
| Mock / Observer          | 独立业务与管理网络，共享私有 journal 卷  | 同 Full                    |
| 发布端口                 | 仅 A / B API 与 Observer，绑定 127.0.0.1 | 同 Full                    |

本入口仅启动当前固定包需要的 worker，不启用宿主 Docker socket、外部模型或未授权出站目标。

## 运行

以下路径为示例，需替换为本次已有源栈和新输出目录。

```sh
backend/.venv/bin/python -m scripts.selftest.profile_stack start \
  --directory /private/tmp/flowtest-compact-example \
  --source-stack-directory /private/tmp/flowtest-standalone-example \
  --profile compact

backend/.venv/bin/python -m scripts.selftest.run \
  --directory /private/tmp/flowtest-compact-example \
  --output-dir /private/tmp/flowtest-compact-example/core \
  --suite fixed-core --rounds 1

backend/.venv/bin/python -m scripts.selftest.run \
  --directory /private/tmp/flowtest-compact-example \
  --output-dir /private/tmp/flowtest-compact-example/extended \
  --suite extended-core --rounds 1

backend/.venv/bin/python -m scripts.selftest.run \
  --directory /private/tmp/flowtest-compact-example \
  --output-dir /private/tmp/flowtest-compact-example/mcp \
  --suite mcp-core --rounds 2

backend/.venv/bin/python -m scripts.selftest.profile_stack stop \
  --directory /private/tmp/flowtest-compact-example
```

Full 使用另一个新目录并传 `--profile full`，其余步骤相同。

## 证据与清理

- `stack.json` 冻结 source / dependency / image identity 和 A / B / Observer 身份。
- `profile-proof.json` 冻结各依赖容器；`profile-compose.frozen.yaml` 保存本次部署配置。
- 每次特权操作前重新检查容器、独立数据库 / 队列 / 存储配置、worker 命令、网络成员、
  镜像、挂载与私有凭据隔离；来源或部署漂移会阻止继续。
- 每轮保留冻结 Manifest、独立 Evidence、Verification 与两种 JUnit。原始预期失败
  仍为 failed，独立 matched 单独记录；MCP 的 selected_suites 不代表全部验收项通过。
- `private.env` 仅本机进程可读。候选 API / Worker 不获得 Observer 管理凭据。
- 清理检查精确 project / nonce 后才 down；确认全部容器、卷和网络消失后才写
  `cleanup.json` 并删除私有材料。未知结果保留失败，不写 completed。

固定资源见 [core-v1](../../selftest/packs/core-v1/manifest.json)、
[extended-v1](../../selftest/packs/extended-v1/manifest.json)。
