# 自测 v2 与 S5 当前验证

2026-10-24。用户要求完成剩余 S5 与全部不依赖模型的验收，真实模型继续不调用。代码位于独立工作树、分支 `codex/mcp-native-selftest`。原始检出的无关修改保留。

## 固定实现

应用源码摘要：`3d11af7e5ca9e3cd66997b0eaf2a4ec9969d551ec688ad191006333bd3d27ac7`。

当前 H/O 为 frozen42：Standalone `bfb71f14d8613b164956bdeaaf5c97b2b7f5578023c24902f49a4b1c5b6a06be`，Full/Compact `d343fb7fcf265b9ff07645caf90d3f7f41e566c5adfe4f578100fa8e2222b8e5`。逐文件来源在本地 `output/selftest-validation-20261024-s5/frozen42/sources/source-receipt.json`，1509 个文件已核对无漂移。应用源码与构建身份独立记录；基线 HEAD `70e4b513e734c2c47053ecc314db0bbd092f16db` 不能替代工作区摘要。

## 实际验证

- 后端全量：3372 passed、15 skipped，覆盖率 91.64%，987.66 秒；日志 `/tmp/flowtest-s5-backend-pytest-all5.log`。格式、Ruff、mypy app 同轮通过。之后仅核验器语义与 CI 命令补强，相关 126 项定向检查通过，未把定向数量加成新的全量结果。
- 前端全量：194 文件、1539 测试通过，statements 86.81%、branches 82.70%、functions 86.74%、lines 89.42%；格式、lint、类型和构建通过。本轮没有在该结果后修改前端源码。
- Mock 42 项通过。最新全部后端/H 格式和 Ruff 通过；现有平铺脚本及 app 类型检查 526 文件，命名空间 H/O 类型检查 211 文件通过。import-linter 1 项架构契约保持；CI 路由及信任 167 项通过。Skill evaluation `--check` 通过。
- Standalone frozen42 完整 CI 入口退出 0：10 个基线批、运行故障 15、协议 34、治理 42、抗误绿 28，另有 12 个扩展包，包括产品边界 27 与编译/草稿 38。所有所属栈精确移除，模型调用 0。本地公开收据：`output/selftest-validation-20261024-s5/frozen42/public/standalone/`。
- Full frozen41 完整入口曾退出 0。之后仅编译独立 O 补强字段、比较符、来源节点、固定 API 及图连通性；frozen42 三形态最终验证继续进行，旧 H 结果保留为历史，不能冒充新 H 门禁。
- Compact frozen41 第一次因 Docker 地址池耗尽未进入场景；第二次基线、worker 等波次通过，产品双批次有一项缺失执行 ID，整轮如实失败并清理。frozen42 独立 Compact 产品 27、编译 38 已通过，精确移除后两项独立 O 均为 0。原失败保留，未认定其根因已经解决；完整新来源会继续观察。
- Standalone 当前来源浏览器验证已完成：普通账户经既有 UI 审核及发布 3 个 Workflow、3 个 Case，确认后启动真实原生执行，独立 O 单独封存；原始 1 项失败、独立 3 项 matched 分别保留。初始化/生成/执行双击均只发 1 次写请求；缺 O、错来源关系和过期证据均不显示当前通过。截图及动作收据位于 `output/playwright/selftest-s5-standalone42/`。Full、Compact 对应浏览器验收继续进行。

## 证据与交付边界

本地验收均为 `local_untrusted`、`ci_fixture`，不表示真人审核或真实模型通过。每包不超过 500 请求、600 秒、100 工具调用，递归深度 1；每个包范围和身份独立，MCP 核心 3 场景不代表全系统 94 项。原始执行和独立核验双 JUnit 分开。

[94 项/341 变体账本](acceptance-matrix.md)保持分母，正在按 frozen42 完整证据更新；旧 profile 通过记录以各自源码收据为准，不构成当前全项通过。当前服务仅启用 stateless；stateful 扩展变体不适用，保留目录记录。稳定 main 缺新自测接口的交叉组合已经实际 OpenAPI 探测，明确不支持，不降级契约制造通过。

真实 Host/LLM、真人修订和 assisted 质量验收继续 NOT_RUN。远程当前提交检查、Windows 原生包、正式 Required Gate、合并后 CI 与完整发布验收分别记录；不能用本地通过推断。涉及治理路径的变更须维护者受控 Bootstrap，不自动合并或自签门禁。

390px 下自测工作区右边界为 378px；既有全局页头使文档宽度 438px，未计为全应用移动端通过。日常 Chrome 与 Docker 数据保持隔离；只回收本任务 nonce 所属资源。

[开发范围与迁移](s5-progress.md)、[CI 分波次及上传白名单](ci-acceptance.md)、[扩充前历史记录](validation-final27-history.md)、[早期失败与构建](s5-development-history.md)。
