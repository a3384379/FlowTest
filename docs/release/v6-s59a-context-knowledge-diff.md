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
- 远程 CI、Compose Playwright 与 PR 复审尚待完成，以 PR 实际结果为准。

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
