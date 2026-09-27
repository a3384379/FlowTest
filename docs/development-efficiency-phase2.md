# 开发效率优化第二阶段实施记录

## 范围与基线

本阶段从第一阶段提交 `ce21e7a74d69597d9c388904102012f265ac4876` 建立独立分支；第一阶段的定向测试入口保持不变。普通 Compose、Security 的触发条件和作业名保持不变，Compact RC 作业未调整。此次不改业务代码、数据库或发布审批。

历史 CI 参考为同一提交 `87b359e1ec821ab136e3c016d037f1149f192163`、同一 attempt 1、`ubuntu-latest`（镜像构建为 linux/amd64）的成功记录。缓存冷暖状态没有可靠记录，因此这些时间只定位瓶颈，不与本机数据计算提速比例。

| 工作流 | 作业耗时 | 可分离的关键步骤 |
| --- | ---: | --- |
| Compose `36025823590` | 30:04 | 启动与构建 15:41；非 S29 浏览器验收 6:33 |
| Security `36025823662` | 21:17 | 构建发布镜像 18:05；后端镜像扫描 1:32 |
| Frontend `36025823528` | 16:24 | 测试 15:24；lint 0:37 |
| Backend `36025823614` | 9:23 | 测试 8:34；格式与 lint 0:37；集成验证另作业 1:27 |

这些作业并行运行，所列作业的最长关键路径为 30:04；四项作业累计 runner 占用为 78:35，**不是**用户等待时间。历史前端初始化、类型检查及构建没有足够独立步骤数据，不能再细分。

本机改动前 profiling：后端 `uv run pytest --no-cov --durations=20` 为 1458 passed、7 skipped，pytest 120.29 秒；前端单 worker `CI=1 pnpm exec vitest run --reporter=json` 为 425 passed、88 个文件，墙钟 232.5 秒。后端慢项包括 Docker 超时映射 5.42 秒与 k6 进程错误路径 3.01 秒；前端 `FlowProposalReviewDialog` 文件 12.90 秒，其中人工接受后应用的用例约 10.01 秒。机器、覆盖率参数与 CI 不同，不能直接横比。

## P2-A：基础层与回退

`backend/Dockerfile` 将昂贵、少变的基础层明确命名为 `python-base-source`、`k6-base-source`、`docker-cli-base-source` 与 `environment-daemon-source`。应用运行时在独立的 `python-runtime` 层才复制依赖清单、锁文件、应用源码及迁移；k6、Docker CLI 和 daemon 仍只进入原来需要它们的目标。原有 CPython tarball SHA256、签名验证、CVE 补丁与回归用例，Go 上游提交校验与补丁版本检查，Alpine 已签名软件包升级及运行用户均保留。

| 基础目标 | 来源与版本 | 平台及补丁输入 | 构建标识 |
| --- | --- | --- | --- |
| `python-base-source` | Debian trixie-slim；CPython 3.13.15，tarball SHA256 `1e66a794…ea4a76` 与上游签名 | CI linux/amd64；本机另验 linux/arm64；`patches/cpython-3.13-cve-2026-82049.patch` | 构建提交 SHA 与镜像 digest 应在发布时记录 |
| `k6-base-source` | Go 1.26.6 固定镜像 digest；k6 2.2.0、gRPC 1.83.2 | 同上；Go 模块校验 | 同上 |
| `docker-cli-base-source` | Docker CLI 29.7.2，上游提交 `a7dcaa6fdb6ed04aacbfdc76357fdae01605609e` | 同上；gRPC 1.83.2 | 同上 |
| `environment-daemon-source` | Docker dind 29.7.2 固定 digest；Moby `6a43e3d5afddf4111da0f864bbc7cae5d7e95001`；containerd 2.3.3 `aad11006b869517fcd3009450b6f82da282e1a9b` | 同上；gRPC 1.83.2、x/crypto 0.56.0、Alpine libblkid/libuuid 2.42.3-r0 | 同上 |

四个 `FLOWTEST_*_BASE` 构建参数默认指向本 Dockerfile 的源码目标，所以冷缓存、尚无基础镜像或缺少某平台时仍可源码构建。发布基础镜像后，应由受信分支或受控人工流程构建、扫描并发布到**已授权**仓库，再按平台把实际发布 digest 写入构建参数；不得改成可变 tag 或编造 digest。目前仓库没有可核实的已授权基础镜像仓库、发布权限或已发布 digest；当前 `gh` 凭据列出该用户 container packages 时返回 HTTP 403，缺少 `read:packages` scope，不能据此确认现有仓库。因此本提交没有切换默认引用，也没有发布基础镜像。过渡期间由独立缓存减少重复编译；真正的远程基础镜像复用仍待发布条件具备。

本机已构建上述四个源码目标（linux/arm64，原有本地缓存命中），并直接验证 Python 3.13.15、Docker CLI/dockerd 29.7.2、containerd/ctr 2.3.3。使用本地临时 tag 输入 `FLOWTEST_PYTHON_BASE` 构建应用时，构建图没有进入 CPython 源码阶段。这个 tag 仅用于本机验证，未提交为正式引用；本地镜像的 digest 无法替代仓库发布的 digest。

## P2-B：构建缓存与当前流水线内复用

`backend/docker-bake.ci.hcl` 为每个 Dockerfile 目标和 linux/amd64 平台分配独立 GitHub Actions BuildKit 缓存 scope，并使用 `mode=max` 保留中间层。缓存导出失败只放弃加速；缓存缺失时仍执行完整构建与原有测试、扫描。后端锁文件及补丁先于业务源码复制；前端依赖清单先于源码复制，`.dockerignore` 排除构建不需要的 E2E 文件。版本、补丁、锁文件与源码变化由 BuildKit 正常使相关层失效。当前方案没有跨工作流传递镜像，也不会用旧 main 应用镜像验证 PR。

Security 在一个 Bake 调用中构建 7 个本仓库扫描目标并加载到同一 Docker daemon，后续扫描直接使用这些镜像；另一个固定 digest 的环境 fixture 仍按原流程单独拉取和扫描。Compose 的普通冒烟在一个 Bake 调用中构建 7 个唯一目标，为 12 个启用服务镜像名加载相同产物，然后用 `docker compose up --no-build --wait`。runner agent 属于其他 Compose profile，不在普通冒烟额外构建。工作流核对实际 checkout SHA、PR head SHA 标签、平台和本地镜像身份；Compose 启动后还核对运行容器的 image ID 与本次加载的 image ID。这里的可信传递关系是**同一作业内的本地构建、加载、扫描或启动**，不是单靠标签自报，也不宣称两个工作流使用同一镜像。

本机 `docker buildx bake --print ci-compose` 与 `docker compose config` 对照，12 个服务镜像名完全覆盖且无多余普通冒烟目标；`--call=check ci-compose` 无警告。linux/arm64 上执行全部 7 个普通冒烟目标的本地 Bake，第一次 13.36 秒，紧接着相同输入的暖缓存重跑 1.90 秒。**第一次已经有本地层缓存，不是冷构建**；使用的是本机 Docker 缓存，不是 CI 的 GHA 缓存。Mock/GRPC 两个 tag 经 `docker image inspect` 确认指向同一 image ID。

另在临时 backend 上下文仅改动 `app/__init__.py` 后重建：基础源码阶段未运行，依赖清单复制与首次 `uv sync` 均为 `CACHED`，应用复制和项目安装重新执行，墙钟 4.09 秒。该实验只验证源码层失效边界；锁文件或补丁变化引起的完整重建依据 Dockerfile 的 COPY 依赖链，尚无冷缓存实测。CI linux/amd64 的跨 runner 缓存命中率、容量与失效行为也待受控工作流实测。

## P2-C：慢测试

Docker 与 k6 超时 fixture 改为 `exec sleep 5`，避免 shell 进程被终止后子进程仍占用管道；超时、失败路径与异常断言不变。Docker 对应用例在同一台本机由 5.42 秒降至定向复测 2.19 秒；k6 相关用例 3.01 秒至 2.89 秒，改善很小，不作整体提速承诺。

前端人工接受后应用用例在每次状态变化后按可访问标签重新查找按钮，避免反复扫描整个页面的可访问角色树；首次按钮角色、禁用状态、接受、应用、重复点击和工作流 ID 断言仍保留。定向单用例 10.44 秒至 9.24 秒；样本各一次，有运行波动。CI 单 worker 设置仍保持，未分片、未调高重试、未改变覆盖率阈值或跳过场景。

## 验证与未完成项

已执行：Dockerfile/Compose Bake 静态检查、四个基础目标本机构建与版本检查、linux/arm64 的 7 个普通 Compose 构建目标、标签 image ID 核对、应用层失效实验、定向后端和前端测试、工作流 YAML 解析、`git diff --check`。后端 `ruff format --check`、`ruff check`、`mypy app` 均通过；`uv run pytest` 为 1458 passed、7 skipped，覆盖率 90.67%，达到原 90% 门槛，pytest 170.18 秒。本机基础目标构建复用了先前缓存，不能替代完整冷构建。前端 `pnpm format:check`、`pnpm lint` 和 `pnpm build` 均通过；`CI=1 pnpm test:coverage` 为 88 文件、425 passed，行/函数/分支/语句覆盖率分别为 87.93%/84.90%/80.72%/85.71%，均达到原 80% 门槛，墙钟 364.76 秒。此前 232.5 秒的本机 profiling 未开启覆盖率，不能与本轮直接计算提速。

由于另一工作区占用默认宿主端口，本机以临时 Compose override 建立独立项目 `flowtest-phase2`，给前后端分配随机本机端口，其他服务不暴露宿主端口；`up --no-build --wait` 的 15 个服务均健康。12 个由本仓库构建的运行容器 image ID 与已加载镜像相同，后端 `/api/v1/live` 与 `/api/v1/ready` 正常，前端返回 HTTP 200。Playwright 执行登录初始化及 1366×768 编辑器导航场景，2 passed（9.1 秒）。本次项目和卷在测试后清理，原有工作区未重启。该冒烟不替代 CI 中完整浏览器验收。

尚未执行或无法宣称通过：CI linux/amd64 冷暖构建、GHA 缓存跨 runner 命中、Security 实际漏洞扫描、CI 完整 Compose/Playwright 验收、跨工作流同一镜像复用、基础镜像发布与 digest 清单。Security 与 Compose 仍分别构建当前 checkout 的应用镜像；若要跨工作流共享经扫描产物，需要第三阶段的门禁拓扑与可信产物传递设计。

`scripts/required_gate.py` 对 `.github/workflows/*` 变更要求受控 Bootstrap。此次两个工作流只改内部构建步骤，正常 PR 的 Required Gate 仍会因 CI 治理文件而阻断；不能用 `ci:light`、删除门禁或伪造检查绕过。需要项目维护者依既有 Bootstrap 流程纳入这两个工作流，并在适用的当前提交上重新运行必需检查。第一阶段提交也尚未进入 `main`，第二阶段分支依赖该提交；远程合并前应先处理这一依赖。

回退方式：工作流回到各自原有 `docker build` / `docker compose up --build` 步骤；Dockerfile 四个参数维持源码目标默认值，任何未发布或缺平台的基础镜像都不会成为默认依赖。禁用持久缓存只影响构建耗时，不影响必需测试和扫描。
