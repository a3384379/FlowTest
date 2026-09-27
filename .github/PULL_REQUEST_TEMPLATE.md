## 本次改动

- 目标与范围：<!-- 本 PR 唯一阶段和可验证交付 -->
- 不包含：<!-- 明确未实施的相关能力 -->

## 验证与状态

- 已执行：<!-- 命令、结果、CI Run；不要粘贴 Secret -->
- 未执行及原因：<!-- 包括完整检查、部署形态或发布验收 -->
- 最新提交的远程合并门禁：<!-- 提交 SHA、必需检查结果；尚未运行时注明 -->
- [ ] 本地定向验证已记录；未将其表述为 CI 或发布验收完成
- [ ] 合并前使用适用的 `ci:light` 或 `ci:milestone`；代码和开发规则改动不用 `ci:light`

## 风险与后续

- 风险、失败模式及回退：<!-- 说明影响范围、监控和可逆性 -->
- 阻断问题与非阻断跟踪：<!-- 真实 P1/P2 缺陷需处理；独立改进可给出后续记录 -->

## 按变更适用性补充

- API / Contract / Fingerprint / Snapshot 兼容影响：<!-- 不适用时注明 -->
- 数据库 migration upgrade/downgrade：<!-- 无数据库变更时注明 -->
- Standalone / Compact / Full 兼容与 Playwright E2E：<!-- 选择适用形态及证据 -->
- Golden / Roundtrip / Failure-path：<!-- 按改动范围 -->
- Backend format / Ruff / mypy / pytest 与 Frontend format / lint / coverage / build：<!-- 说明已运行和未运行项 -->
- 安全、授权、租户隔离和不可信输入：<!-- 按改动范围 -->
- 数据分类、加密、Rotation、Retention、Export、Support Bundle：<!-- 新字段或数据路径适用 -->
- 外部错误信封和 Trace ID：<!-- 外部错误变更适用 -->
- 人工审批与权限范围：<!-- 高风险操作适用 -->

现有授权诊断采集遵循请求级安装/项目策略：默认 OFF 不扫描、替换或阻断已授权值；ON 使用既有脱敏。不扩大采集。Review Thread 以问题是否仍真实存在及证据判定；阻断缺陷须解决，非阻断建议可记录后续跟踪。
