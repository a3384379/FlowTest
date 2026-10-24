# S5 远程验收修复与新来源

2026-10-24。[PR #151](https://github.com/a3384379/FlowTest/pull/151) 首轮 Bootstrap 运行 `40070339838` 暴露依赖审计、隔离 MinIO 镜像拉取和浏览器回归问题。保留失败记录，不把旧提交的成功子检查移作新提交的正式门禁。真实 Host/LLM 调用仍为 0。

## 修复内容

- Python 审计发现 7 项已知漏洞，集中在四个包。按官方修复版本更新 [filelock](https://github.com/tox-dev/filelock/security/advisories/GHSA-v4x8-3wr5-3wq8)、[graphql-core](https://github.com/graphql-python/graphql-core/security/advisories/GHSA-vj8h-fx38-h3vc)、[OpenTelemetry](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h) 和 [setuptools](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w)，仅同步必需的 OpenTelemetry 依赖。`pip-audit` 复核无已知漏洞；可编辑安装的本项目不在 PyPI 审计范围。
- 前端两个高危传递依赖按受影响版本区间定向约束到 [Zod 4.6.6](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5) 和 [Undici 8.12.2](https://github.com/advisories/GHSA-xjj6-f33q-929c)。`pnpm audit --audit-level high` 退出码 0，仍报告 3 项 moderate，未降低现有审计阈值。CI 固定 pnpm 11.16.0 实测接受新的 frozen lockfile。
- 自测专用 DockerHub MinIO 镜像实际返回 pull denied，未进入场景。改用主部署已经采用的 `cgr.dev/chainguard/minio@sha256:bd014394a80898e68c149f2311fdf8d5a2c2f3bb2c33b9327ae6d02b4b065ae1`，同步其用户和 bash TCP 健康检查。继续核对容器健康、镜像 ID 和网络/卷归属，未放宽隔离或证据判断。
- Linux 浏览器稳定复现 N10 失败：打开组织治理页自动选择首个组织，触发全局缓存清理、子树重建并卸载项目下拉框。默认展示治理组织改为只读选择；用户明确选择治理组织时才更新全局作用域。增加先失败再通过的回归，并保留显式选择与离开页面后的组织选择。原 N10 浏览器断言未修改，修复后通过。

## 冻结 46 的本地补验

应用摘要 `77bab6458cdf165ba18847eff080673e3b5b0ffb6e71bba72de61c27cef6883c`；Standalone H/O 摘要 `bfb71f14d8613b164956bdeaaf5c97b2b7f5578023c24902f49a4b1c5b6a06be`；Full/Compact H/O 摘要 `c5bf5b287ae9dec06590c1346e487be24b8ed1a017e67cc66be7b34874f1b75d`。Compose 文件另由 profile proof 的实际摘要约束。应用镜像重新构建并包含更新后的依赖。

- 后端协议、健康、Standalone、MCP、设计编译与产品 API 114 项通过；profile/clone/CI 信任 66 项通过。Backend/H Ruff、格式和 mypy 通过。
- 账本与 CI 计划/Required Gate 的本地回归 148 项通过；该测试不发布远程门禁。
- 更新前端依赖后全量 194 文件、1539 测试通过；statements 86.81%、branches 82.70%、functions 86.74%、lines 89.42%；格式、lint、类型和构建通过。之后组织作用域修复的四个相关文件 79 项通过，显式选择另补 1 项通过，lint 与构建通过。该专项不冒充修改后的另一次本地全量。
- 新 Compact 栈实际完成 `ST-API-008-product-files` 原生上传、下载、摘要/归属校验，独立 O matched。销毁前保持待清理退出码 2，精确销毁后最终退出码 0。公开补验位于本地 `output/selftest-validation-20261024-s5/frozen46/public/`，范围为 `diagnostic_subset`，不替换冻结 45 的三形态完整入口。

Linux Chromium 1.62.1 导航与编辑器两份原有 E2E 共 13 项通过，包含 1280×800、1440×900、1920×1080 的 27 个状态及真实执行/历史快照。截图基线仅更新新增组织选择器所在的前 56 行像素，原图其余像素逐一保持相同；原 `maxDiffPixelRatio: 0.003`、mask 和业务断言均未修改，最终不带 `--update-snapshots` 的完整断言运行退出码 0。审阅记录在本地 `frozen46/public/header-baseline-review.json`，截图在 `output/playwright/selftest-s5-editor46/`。该补验使用独立 localhost、生产前端构建和隔离 Standalone 后端，私有测试配置未修改应用安全策略；较早非 localhost 测试地址缺少安全上下文、代理 Host 丢失端口等试验失败保留，未计通过。

最新提交的全量远程检查、三形态安全工件和 Windows 原生包以 PR 实际运行结果及本地 `output/selftest-validation-20261024-s5/remote/` 补充记录为准；本文件不预告成功。

## 后续探针与组织切换补修

提交 `bcf7f2e`、tested merge `2135c723153e329d83ca8f49767dd7b9cdaa2d1d` 的 Bootstrap `40072818119` 已实际通过后端全量（3386 passed、20 skipped、91.64%）、15 项数据库集成、源依赖和镜像安全、Windows、升级回退、Quick、Skill 及 Standalone 全套自测。Windows 实际预检确认 55 个 MCP 工具；下载的外层工件摘要与包内发布 SHA-256 均匹配。该提交 Full 在协议探针阶段失败，Compact 基线完成但配置类扩展失败；前端全量有 4 项组织切换前置操作失败，Compose 有 S28 弹窗超时及 Service Account header 首次不匹配。均保留原失败工件，不能用成功子检查推导整体通过。

- 独立 Full 栈重新执行 34 个协议场景，实际全部 matched，销毁后独立核验退出码 0，未复现远程该次失败。单独的 `diagnostic_subset` 证据位于本地 `frozen47/public/`，不能替代远程整轮。
- 对共享的探针账号初始化增加真实接口延迟回归：每次创建账号延迟 1 秒，旧实现稳定收到 `422 SERVICE_ACCOUNT_EXPIRY_INVALID`。原因是 3 秒期限在其它账号创建前就开始计算。改为首先创建待过期账号、初始期限为 30 秒，并继续等待真实时钟过期；不移动批次截止时间，不重放未知写入，也不放宽过期账号的拒绝断言。协议、故障、质量等配置共用该夹具。旧远程工件缺少细分原因，尚不能据此断言这就是两次远程失败的唯一原因。
- 复用原有安全错误码提取器，将已有类型化失败报告和双 JUnit 投影到原有 CI 公开白名单目录；协议和配置组的初始化原因不再只剩通用错误。只投影错误码及已采集的类型化报告，不公开原始异常文本、SDK 帧、环境或令牌。已有输出仍拒绝重跑和覆盖，缺报告、额外 finding、伪成功及最终处置失败继续阻断。
- 治理组织使用显式选择事件，选择当前已经显示的默认选项也会激活正确的组织 header；浏览页面本身不改变全局域。新增先失败再通过的同选项回归。4 项跨组织迟到响应测试也改为实际选择组织，原缓存失效范围和会话隔离断言保留；全部使用合成响应，模型调用 0。
- S28 原测试选择资产后多按一次 Escape，会在下拉框已关闭时取消父弹窗。改为等待下拉框关闭并确认父弹窗仍可见，再提交；映射 201、覆盖矩阵及证据断言全部保留。Linux 原有 N10、S28、Service Account 三个业务用例及登录 setup 共 4 项，`--retries=0`，实际一次通过；后者保持关闭令牌截图、视频和 trace。

该次 H/CI 核心专项 91 项、输出复用与配置报告补验 40 项通过；前端四个相关文件 81 项、跨组织迟到响应 4 项通过，格式、lint、类型和构建通过。修改后的前端完整检查实际为 194 文件、1542 测试通过，450.28 秒，覆盖率 statements 86.81%、branches 82.70%、functions 86.74%、lines 89.42%，日志 `/tmp/flowtest-s5-frontend-coverage48-final.log`，退出码 0。远程新提交验收仍须看最终实际结果，不从本地通过推断。应用摘要保持 `77bab6458cdf165ba18847eff080673e3b5b0ffb6e71bba72de61c27cef6883c`；新 H/O 摘要为 Standalone `ceda375cd795a4005aa45b4b225a59c6e2e588df5c75e02d17c56c9bcad4186d`、Full/Compact `55e6df698617e722362458b7fb24a4f5453c80b5aa956c7929a7875ad503d26b`。原冻结 45/46/47 收据不改写。

新 H/O 的真实 Compact 配置组另完成 14 个故障、18 个质量、12 个审核场景，共 44 个，均由独立 O 匹配。处置前保持待清理退出码 2，精确处置后原 CLI finalizer 退出码 0；所属基础栈和 Compact 栈均清理完成。该 `selected_suites` 补验位于本地 `output/selftest-validation-20261024-s5/frozen49/public/`，不冒充完整三形态远程运行。

## 网关启动与取消回收补修

提交 `7737f84`、tested merge `d372b3dab5028e13e0ec79674bbaeff2f6d353a4` 的 Bootstrap `40076837078` 已通过后端全量（3391 passed、20 skipped、91.64%）、数据库集成、安全、Windows、升级回退、Quick、Skill、Compose 业务与浏览器验收及 Standalone 完整自测。Standalone 公开工件的外层 SHA、10 批基线、12 包扩展、来源身份、双 JUnit 和精确处置已下载核对；核对不等于在本地重算未公开的原始证据。

该轮 Compact 的新安全失败报告明确为 `SELFTEST_TIMEOUTERROR`，发生于协议阶段，整步耗时约 353 秒，不能归因于 600 秒批次截止时间。检查剩余超时路径并新增先失败的回归，确认旧网关的 15 秒冷启动限制会截断 16 秒启动，启动取消也没有回收控制子进程。冷启动改为最多 45 秒且重新取原冻结截止时间的剩余值，降低就绪探测频率；控制子进程取消时精确 kill/wait。退出等待仍为 5 秒，超时后回收所属 CLI，保持清理未完成；启动和退出超时分别输出明确错误码。没有延长包截止时间、重放写入或放宽独立核验。

网关、CI 信任、协议归档和配置组共 70 项本地测试通过；再加入实际协议传输、独立 O、配置取消、CI 扩展和读取器回归，最终联合 143 项通过（25.55 秒）。H/O mypy 211 文件、backend/H 全部 1041 文件格式与 Ruff 通过。新增回归涵盖延迟启动、已冻结的短截止时间、取消回收和退出超时不能记作清理成功。该回归证明真实缺陷存在，但不能仅凭它断言旧远程超时的唯一原因；修复后的远程整轮仍须单独完成。应用摘要保持不变；此轮新 H/O 摘要为 Standalone `b7d8ffba71321ddc284e87512739f0c5f06e27c3325a241c42d4c5390d0f1f2e`、Full/Compact `42bc908f4254a8ca7c027f30abc523f6cf817dd3e0e69dc3cc636042dc5542d3`。

新 H/O 的真实隔离 Compact 栈已通过协议 34、治理 42，共 76 场景；处置前仅因待清理保持退出码 2，精确处置后原 CI finalizer 重算均为 0，网关及基础/Profile 栈清理完整，模型调用 0。本地安全投影位于 `output/selftest-validation-20261024-s5/frozen50/public/`，范围为 `selected_suites`，未用补验冒充完整远程运行。

该轮 Full 作业在 40 分钟总时限被取消。下载核对的工件中，10 批基线与 13 包扩展均已通过，但扩展总收据在 `08:48:14Z` 才完成，CI 在 `08:48:16Z` 中止进程，最后基础构建栈的退出清理没有完整成功证据，故作业不能计通过。仅将三形态自测作业的总时限改为 60 分钟，容纳约 7 分钟的冷构建、多个串行有界波次及最终清理；每包 600 秒及请求/工具预算、独立核验和失败阻断保持原值。CI 路由、Required Gate、H/O 信任边界共 167 项回归通过，工作流和文档格式通过。新提交仍须实际整轮退出成功。

## 编译入口的安全失败投影

提交 `3111ac9`、tested merge `6db403a54fc6633c3e6fb195b0d8237ef0066628` 的 Bootstrap `40079734753` 已完成：后端 3395 passed、20 skipped、91.64%；前端 194 文件、1542 测试，四项覆盖率为 86.81%、82.70%、86.75%、89.42%；数据库集成 15 项；安全、Windows、升级回退、Quick、Skill、Compose 业务和浏览器全部通过，主浏览器批次 68 项通过。Standalone 的 10 批基线/12 包扩展、Compact 的 10 批基线/13 包扩展，均已下载核对 SHA、冻结分母、来源、双 JUnit 和清理。Windows 新包发布校验和匹配，实际原生预检 55 工具。

Full 的 10 批基线和前 11 个扩展包通过，最后纯编译/草稿边界 CLI 以非预期状态退出，工件只记录 `SELFTEST_EXTENDED_STAGE_FAILED:compiler-boundaries`，未公开底层类型化原因，整轮失败，清理完整。另建两轮隔离 Full，产品 27 + 编译 38 均通过，未复现远程异常：第一轮 H/O `42bc908f4254a8ca7c027f30abc523f6cf817dd3e0e69dc3cc636042dc5542d3`，第二轮中间诊断版 H/O `ec3e390ff126d10e4d042013c6263f029181a28b672318b72d92ebd998d8f0cb`。本地 `frozen70/`、`frozen71/` 保留各自安全报告、已验证摘要的 H/O 源码和精确清理证明，不计作远程通过。

编译 CLI 现在将已有异常投影为安全类型化失败报告，固定 38 项分母、空 matched、退出码 2；已有输出仍拒绝重放，最终处置的次生错误另存且不覆盖第一份失败。CI 仅公开这些报告及已经采集的阶段退出码，缺独立报告、异常或处置不完整继续阻断。原有私有 stderr 保留，SDK 原始帧、环境和凭据不进入公开工件。先失败的三项回归确认旧实现确实缺少投影/非重放行为；最终相关 136 项通过，mypy 211 文件、backend/H 格式和 Ruff 通过。该补修改善可定位性，不声称已经证明远程异常的根因。新 H/O 为 Standalone `c046bc90111f82be4b0d29f6d2bea64582998966f391066e1a189f09ad46f641`、Full/Compact `5c5ebbea6750aa29a5fdf47fdd0720600d7813f0595b72b14e3f105ca5f57c33`；应用摘要不变。新完整远程运行须实际核对后才能认定通过。

旧执行报告截图在数据加载完成前截取，另用独立 Chromium、普通测试用户、真实 H/O 完成报告页补验：3 场景 matched，1 个原始 failed 保留，加载后的来源链、生成来源、错误来源拒绝和提案回链均确认；原始 JUnit 保留 1 个 failure，核验 JUnit 无 failure。证据位于本地 `output/playwright/selftest-s5-loaded55/`，仅为 `selected_suites`。使用 `ci_fixture` 审核，不计真人审核，模型调用 0；浏览器、代理及所属测试栈均已清理。较早 origin/CLI 包装/待审核定位失败尝试也保留，不计通过。

## 验收边界

[冻结 45](current-validation.md) 和 Git 账本保留当时来源与原始结果。后续补验按新的应用、H/O、镜像和 PR head/tested merge SHA 单独归档。真实模型按用户要求 NOT_RUN；治理文件按 `AGENTS.md` 要求仍需维护者受控 Bootstrap 审查，诊断成功不发布正式 Required Gate、不自动合并或调整规则集。合并后 CI、真人审核和完整发布验收仍是不同边界。
