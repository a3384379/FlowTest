# S59A Context Diff / Knowledge Diff

## 基线与范围

S59.0 PR #80 与 PR #82 已普通合并；PR #82 合并后七项 main 工作流均已成功。S59A 从该全绿 main
创建独立分支，实现版本化 Context/Knowledge Diff 与授权只读接口。

PR #82 仍有一项接受的 P2：来源标签依赖调用者可控的 `source_ref`，后续 S59C 必须依据持久化可信
Provenance 分类。审查线程关闭表示接受技术债，不表示该缺陷已修复。

## 交付

- 纯领域 Context Diff：证据、Provider/来源版本、契约/数据/测试版本、完整性、冲突。
- 纯领域 Knowledge Diff：节点身份、Kind、标签指纹、变化 Fact 名、关系；包括 State Candidate。
- Context Inspector 同项目、同 Context 的固定历史版本比较接口，支持同版本与反向比较。
- Diff 不包含节点 Fact 值、标签原文、Conflict Summary、源码或数据库原始行。
- Golden、顺序稳定性、多版本、多值 Fact、最大图差异和项目隔离回归。

设计边界见 [ADR 0049](../adr/0049-context-knowledge-diff.md)。本阶段不产生或自动接受、应用、发布 Patch。

## 验收状态

- 本地集中后端验收：Ruff Format / Ruff Check / Mypy 全部通过。
- 全量 Pytest：1032 passed / 4 skipped；覆盖率 90.95%，达到 90% 门槛。
- PR #83 最终候选复审无未解决行内线程，远程子工作流与 Required Gate 全部成功，已普通 Squash 合并。
- 合并后 main 的 Backend、Windows Bundle、Upgrade、Security、Compose 与 Required Gate 均成功。
  Required Gate Controller：`33957102399`；Compose：`33957102389`。

S59B 在本阶段合并后继续；当前不能将整个 S59 标记为完成。

## PR #83 依赖门禁修复

S59A 首轮自动复审完成且无行内发现。Security CI 在 performance 镜像发现
`GHSA-vp52-pcj8-j9qc`：嵌入的 `google.golang.org/grpc v1.83.0` 受影响。
[gRPC 上游公告](https://github.com/grpc/grpc-go/security/advisories/GHSA-vp52-pcj8-j9qc)
确认修复版本为 `1.83.1`。

- 保留 k6 2.2.0、Docker/Moby 29.7.2、containerd 2.3.3 及 Go 1.26.6 基线。
- 在相关 Go 构建阶段统一选取 gRPC 1.83.1；Docker CLI 保持其 vendor.mod/vendor.sum 布局。
- 增加 k6、dockerd、containerd、ctr 二进制内嵌模块版本检查；Docker CLI 采用 GOPATH 构建，
  校验实际参与编译的 `vendor/modules.txt` 中精确 gRPC 版本。不新增漏洞忽略项、不降低扫描级别。
- 本地定向构建在 GitHub/Go 模块下载或校验阶段遇到 TLS EOF，不能记为编译通过；远程构建和扫描仍待验证。
- Python/前端业务代码未因此修改，不重复运行已通过的本地全量测试。

增量复审已完成且无发现。第二轮远程构建证明 Docker CLI 已成功编译，但原先对其执行的
`go version -m` 模块断言不适用于 GOPATH 构建，导致 Security/Compose 失败；已改为上述 Vendor
精确版本断言，Dockerfile 静态检查通过。本地构建仍在 GitHub 下载阶段遭遇 TLS EOF。

同轮 Backend CI 的既有 `test_running_workflow_can_be_cancelled` 出现 SQLite `database is locked`；
本地连续三次定向测试均通过，未修改取消流程或放宽断言。后续候选仍须通过远程后端门禁。

第三轮远程 Backend/Windows/Upgrade 已通过，所有发布镜像构建成功，backend/frontend/performance/
environment/runner 五个镜像扫描通过。daemon 扫描继续发现基础镜像遗留组件：

- 固定基础镜像中的 `containerd-shim-runc-v2` 内嵌 gRPC 1.80.0：本地读取二进制元数据确认，
  将同一 containerd 源码构建的修复后 shim 一并替换，而不只替换 containerd/ctr。
- dockerd 内嵌 x/crypto 0.54.0：更新为 0.56.0，覆盖
  [GO-2026-6354](https://pkg.go.dev/vuln/GO-2026-6354) 和
  [GO-2026-6355](https://pkg.go.dev/vuln/GO-2026-6355)。
- Alpine 的 libexpat 与 OpenSSH：临时容器实际升级验证分别达到 2.8.4-r0 和 10.3_p1-r1；
  仅扩大现有 `apk upgrade` 的相关补丁包名单，不启动业务容器或修改持久卷。

后续仍须以修复候选 Security/Compose/Required Gate 结果完成验收，不将已定位或已修改记为已通过。

后续 daemon 扫描确认 Go 组件问题消失，但系统包 libblkid/libuuid 仍缺少 2.42.3-r0 补丁。
为避免逐包遗漏，现将固定 Alpine 发行版内的 `apk upgrade` 改为覆盖全部已安装包，不切换发行版。
临时容器完整升级成功，libblkid/libuuid 均达到 2.42.3-r0，libexpat/OpenSSH 补丁也保持有效。
本地对固定 environment fixture 的提前扫描因漏洞库下载 EOF 未完成；其结论仍由远程扫描提供。

### 最新候选的阻塞定位（2026-09-05）

完整 `apk upgrade` 候选的 Backend、Standalone Windows、Upgrade CI 已通过，但 Security CI
`33952696164` 仍在 daemon 扫描失败：x86_64 镜像的 libblkid/libuuid 保持 2.42.1-r0。构建日志
确认升级命令成功，其他 11 个包已更新，这两个包未进入升级事务；不是扫描旧镜像或构建失败。

[Alpine 3.24 x86_64 官方目录](https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/)
仍列出 libblkid 2.42.1-r0；此前本地 aarch64 升级结果不能代表 CI 架构的补丁可用性。
[util-linux 2.42.3 发布说明](https://www.kernel.org/pub/linux/utils/util-linux/v2.42/v2.42.3-ReleaseNotes)
将四项高危 CVE 定位于 mount/libmount（76642、78409、78410）及 nsenter/unshare（78408），
而本轮高危匹配对象只有 libblkid/libuuid。存在来源包级误报的可能，不能直接据此关闭发现。

本地原始诊断镜像的 mount 为 BusyBox 链接，未安装 libmount/mount/util-linux 包；但 x86_64
诊断镜像下载遇到 TLS EOF，跨架构索引查询又因签名不匹配失败，均未绕过校验。若选择精确误报
例外，必须先获确认，并在实际 CI 镜像中断言受影响组件不存在，严格限定 CVE、包名与版本；
当前没有新增忽略项、没有降低门禁，也没有重新触发完整 CI。PR #83 尚未合并。

### 无扫描豁免的补丁候选

后续查到 [Alpine 官方 edge x86_64 目录](https://dl-cdn.alpinelinux.org/alpine/edge/main/x86_64/)
已提供 libblkid/libuuid 2.42.3-r0。采用有界补丁安装：先执行稳定源升级；仅当单个库未达到
2.42.3-r0 时，下载并用 APK 正常签名与依赖校验安装该库的固定版本官方包。不添加 edge 软件源、
不切换发行版、不使用 `--allow-untrusted`，也不增加 Grype 忽略项。

独立 `environment-daemon-base` 构建阶段包含每个库的最低版本断言、动态库加载检查及 ext4/btrfs
工具启动检查，可用于本地或显式定向构建。CI 保持原工作流，不调整受保护的治理文件。
本地原始镜像已验证版本断言能拒绝旧版本、接受既有版本，库检查和工具命令均正常；补丁包下载
仍遇到 TLS EOF，不能记为补丁安装通过。x86_64 补丁安装、Compose 和完整 Security 结果待远程验证。

amd64 基础镜像已成功下载；定向构建在稳定源 APKINDEX 的 TLS 连接处失败，尚未进入补丁安装。
Dockerfile 静态检查无警告，改动的 Workflow 与文档 Prettier 检查通过。不重复运行 Python/前端
业务测试，现有候选的 Backend/Windows/Upgrade/Compose 均已通过；新候选仍须通过远程 Required Gate。

### 补丁验证结果与治理修正

候选 `6e49be7` 的 Backend、Windows、Upgrade、Security、Compose 五项工作流均成功。
Security 日志确认 x86_64 的 libblkid/libuuid 均通过正常 APK 校验，从 2.42.1-r0 升级到
2.42.3-r0，两个库各自的安装事务均只升级一个包；所有发布镜像扫描通过，没有扫描豁免。

但 Required Gate Controller `33954803223` 拒绝普通 PR 修改 `.github/workflows/security-ci.yml`。
此前增加的提前构建命令违反了现有治理约束，现已撤回该行，工作流恢复为基线内容；保留已验证
的 Dockerfile 修复与定向基础层。不得绕过 Required Gate，也不得把五项子工作流成功称为可合并。
修正候选随后正常通过 Required Gate 并完成合并；以下最终证据覆盖前述中间态。

### 最终闭环

- PR：[a3384379/FlowTest#83](https://github.com/a3384379/FlowTest/pull/83)。
- 最终候选：`024f880f3e92452cb682da6f7c67a8600e619324`。
- 合并提交：`05d265777fb750d60beb3949c34d573e50954c20`。
- PR 与合并后 main 门禁均成功；没有工作流豁免、漏洞忽略或管理员绕过。
- 按用户要求，当前及后续实机测试（含公司 Windows 实机）不再要求；保留 Windows 自动化与 Compose。
  不将“不再要求”记为“测试通过”，其他 GA 审批也不因此自动完成。
