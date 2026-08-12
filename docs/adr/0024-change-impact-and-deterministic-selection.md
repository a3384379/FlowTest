# ADR 0024：变更影响与确定性测试选择

## 状态

已接受，S28 实现。

## 背景

Git 文件变更、OpenAPI、GraphQL 和 gRPC Schema 变更需要统一回答“哪些资产受影响、应该执行哪些
测试、哪些变更仍无覆盖”。答案必须可重复、可解释并保留历史证据，不能通过执行用户脚本、拉取不可信
仓库或不可审计的启发式猜测得到。Diff、Schema、映射与测试资产都属于不可信输入。

## 决策

1. S28 只接收标准 Unified Diff 或请求中明确提供的 OpenAPI、GraphQL SDL、gRPC Proto 前后版本。
   平台不访问外部 Git、不接收仓库地址或凭据，也不运行用户命令、Hook、Compose 或脚本。
2. 框架无关领域解析器将四类输入规范化为有稳定键的 Change，并限制原文 2 MB、Git 500 个文件、
   100,000 行、单次 5,000 个 Change。OpenAPI 复用已登记 Operation 与 Breaking Change 语义；
   GraphQL/Proto 只比较受控的类型和方法形状。
3. 项目 Owner/Editor 通过 Asset Mapping 把精确或尾部 `*` Source Selector 映射到项目内已有的
   Test Case、Workflow、OpenAPI Contract、Pact Contract 或 Performance Scenario。服务层验证项目授权、
   目标类型和目标存在性，单项目最多 2,000 条 Mapping。
4. `explicit_mapping_v1` 是 S28 唯一选择策略。它按稳定键排序并去重，保存每个选择的 Mapping、变更、
   目标和中文可展示原因；没有显式证据的变更进入 Coverage Gap，不以名称相似度或生成式模型猜测。
5. PostgreSQL 保存不可变 Impact Run、规范 Changes、Change→Impacted→Recommended 图、Test Selection、
   Coverage Snapshot、Gap、摘要和 SHA-256 Fingerprint。重复输入产生相同 Fingerprint，历史查询不依赖
   当前 Mapping 或瞬时前端状态。
6. S28 只生成推荐集合和覆盖证据，不自动执行测试、不修改 Quality/Release Gate，也不把 Coverage
   百分比解释为容量或发布成功。功能由默认关闭的 `IMPACT_ENGINE` Feature Flag 隔离。

## 结果

- 四类变更使用同一套可复现证据和中文 Coverage Matrix 展示，选择原因可从目标回溯到具体变更与 Mapping。
- 显式 Mapping 比启发式推荐保守，需要团队持续维护；代价通过明确 Gap 暴露，而不是用不可验证结果隐藏。
- 后续若引入代码索引、静态分析或 AI Change Set，必须作为版本化的新证据源和选择策略另行评审，不能
  改写 `explicit_mapping_v1` 的历史语义。
