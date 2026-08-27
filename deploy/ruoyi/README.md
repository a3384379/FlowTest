# 若依本地测试目标

该配置用于把官方 `yangzongzhuan/RuoYi` 主分支作为 FlowTest 的本地测试目标运行。

## 启动

在 FlowTest 仓库根目录执行：

```bash
docker compose -f deploy/ruoyi/compose.yaml up -d --build
```

首次启动会在 Docker 内使用 JDK 17 和 Maven 构建若依，并初始化独立的 MySQL 数据卷。初始化脚本强制使用 `utf8mb4`，避免中文数据乱码。

## 地址和账号

- 若依：<http://localhost:8088>
- MySQL：`localhost:13306`，数据库 `ry`
- 若依默认账号：`admin` / `admin123`
- FlowTest 容器内访问若依：`http://ruoyi:8080`

宿主机端口 `8088` 和 `13306` 与当前 FlowTest 使用的端口隔离。若依容器加入了现有 `flowtest-compact_default` 网络，便于 FlowTest 的执行器直接访问。

## 停止和查看日志

```bash
docker compose -f deploy/ruoyi/compose.yaml stop
docker compose -f deploy/ruoyi/compose.yaml logs -f ruoyi
```

如需连同若依数据一起重新初始化，确认不再需要现有测试数据后再执行：

```bash
docker compose -f deploy/ruoyi/compose.yaml down -v
```
