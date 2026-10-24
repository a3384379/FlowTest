# S5 远程验收修复与新来源

2026-10-24。[PR #151](https://github.com/a3384379/FlowTest/pull/151) 首轮 Bootstrap 运行 `40070339838` 暴露依赖审计、隔离 MinIO 镜像拉取和浏览器回归问题。保留失败记录，不把旧提交的成功子检查移作新提交的正式门禁。真实 Host/LLM 调用仍为 0。

## 修复内容

- Python 审计发现 7 项已知漏洞，集中在四个包。按官方修复版本更新 [filelock](https://github.com/tox-dev/filelock/security/advisories/GHSA-v4x8-3wr5-3wq8)、[graphql-core](https://github.com/graphql-python/graphql-core/security/advisories/GHSA-vj8h-fx38-h3vc)、[OpenTelemetry](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h) 和 [setuptools](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w)，仅同步必需的 OpenTelemetry 依赖。`pip-audit` 复核无已知漏洞；可编辑安装的本项目不在 PyPI 审计范围。
- 前端两个高危传递依赖按受影响版本区间定向约束到 [Zod 4.6.6](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5) 和 [Undici 8.12.2](https://github.com/advisories/GHSA-xjj6-f33q-929c)。`pnpm audit --audit-level high` 退出码 0，仍报告 3 项 moderate，未降低现有审计阈值。CI 固定 pnpm 11.16.0 实测接受新的 frozen lockfile。
- 自测专用 DockerHub MinIO 镜像实际返回 pull denied，未进入场景。改用主部署已经采用的 `cgr.dev/chainguard/minio@sha256:bd014394a80898e68c149f2311fdf8d5a2c2f3bb2c33b9327ae6d02b4b065ae1`，同步其用户和 bash TCP 健康检查。继续核对容器健康、镜像 ID 和网络/卷归属，未放宽隔离或证据判断。
- Linux 浏览器稳定复现 N10 失败：打开组织治理页自动选择首个组织，触发全局缓存清理、子树重建并卸载项目下拉框。默认展示治理组织改为只读选择；用户明确选择治理组织时才更新全局作用域。增加先失败再通过的回归，并保留显式选择与离开页面后的组织选择。原 N10 浏览器断言未修改，修复后通过。

## 新来源的本地补验

应用摘要 `77bab6458cdf165ba18847eff080673e3b5b0ffb6e71bba72de61c27cef6883c`；Standalone H/O 摘要 `bfb71f14d8613b164956bdeaaf5c97b2b7f5578023c24902f49a4b1c5b6a06be`；Full/Compact H/O 摘要 `c5bf5b287ae9dec06590c1346e487be24b8ed1a017e67cc66be7b34874f1b75d`。Compose 文件另由 profile proof 的实际摘要约束。应用镜像重新构建并包含更新后的依赖。

- 后端协议、健康、Standalone、MCP、设计编译与产品 API 114 项通过；profile/clone/CI 信任 66 项通过。Backend/H Ruff、格式和 mypy 通过。
- 账本与 CI 计划/Required Gate 的本地回归 148 项通过；该测试不发布远程门禁。
- 更新前端依赖后全量 194 文件、1539 测试通过；statements 86.81%、branches 82.70%、functions 86.74%、lines 89.42%；格式、lint、类型和构建通过。之后组织作用域修复的四个相关文件 79 项通过，显式选择另补 1 项通过，lint 与构建通过。该专项不冒充修改后的另一次本地全量。
- 新 Compact 栈实际完成 `ST-API-008-product-files` 原生上传、下载、摘要/归属校验，独立 O matched。销毁前保持待清理退出码 2，精确销毁后最终退出码 0。公开补验位于本地 `output/selftest-validation-20261024-s5/frozen46/public/`，范围为 `diagnostic_subset`，不替换冻结 45 的三形态完整入口。

Linux Chromium 1.62.1 导航与编辑器两份原有 E2E 共 13 项通过，包含 1280×800、1440×900、1920×1080 的 27 个状态及真实执行/历史快照。截图基线仅更新新增组织选择器所在的前 56 行像素，原图其余像素逐一保持相同；原 `maxDiffPixelRatio: 0.003`、mask 和业务断言均未修改，最终不带 `--update-snapshots` 的完整断言运行退出码 0。审阅记录在本地 `frozen46/public/header-baseline-review.json`，截图在 `output/playwright/selftest-s5-editor46/`。该补验使用独立 localhost、生产前端构建和隔离 Standalone 后端，私有测试配置未修改应用安全策略；较早非 localhost 测试地址缺少安全上下文、代理 Host 丢失端口等试验失败保留，未计通过。

最新提交的全量远程检查、三形态安全工件和 Windows 原生包以 PR 实际运行结果及本地 `output/selftest-validation-20261024-s5/remote/` 补充记录为准；本文件不预告成功。

## 验收边界

[冻结 45](current-validation.md) 和 Git 账本保留当时来源与原始结果。后续补验按新的应用、H/O、镜像和 PR head/tested merge SHA 单独归档。真实模型按用户要求 NOT_RUN；治理文件按 `AGENTS.md` 要求仍需维护者受控 Bootstrap 审查，诊断成功不发布正式 Required Gate、不自动合并或调整规则集。合并后 CI、真人审核和完整发布验收仍是不同边界。
