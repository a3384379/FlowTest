# MCP 环境生命周期生成接入

本入口实现 `ST-MCP-023` 的生成、审核、固定 Workflow 和 Case;执行、独立采证和批次判定由根运行器接续。
它属于确定性 MCP 协议路径,不代表真实宿主、Skill 或模型已运行。

## 调用契约

实现位于 [generation_lifecycle.py](../../scripts/selftest/generation_lifecycle.py)。
根目录使用仓库 `backend/.venv/bin/python` 运行;其环境需能导入 `scripts` 与 `app`。
未使用可编辑安装时,可设置 `PYTHONPATH=.:backend`。

```python
asset = await generate_lifecycle(
    client,
    reviewer,
    installation=installation,
    binding=binding,
    batch_key=batch_key,
    output_dir=batch_directory / "ST-MCP-023",
)
```

- `client`: 已完成真实 MCP discover 的 `ProtocolClient`,其 `batch_key` 必须相同。
- `reviewer`: A 的既有公开 REST 审核身份,审核者与 MCP 生成身份分离。
- `installation`: 已核实的隔离安装;必须有 B 项目、组织、合成 actor、A 目标 Service/Environment 和 reviewer 标识。
- `binding`: 已由启动器核验身份的 `StackBinding`;H 仅通过 `target_url` 读取实际 B OpenAPI。
- A 中 `SELFTEST_B_PASSWORD` 必须已经作为加密 Secret 存在,流程只引用模板,不接收或持久化明文密码。

## 实际生成路径

1. H 读取 B `/openapi.json`,选出 login 与环境 POST/GET/PATCH/DELETE 五个真实操作及其递归组件引用。
2. 绑定唯一的 `target_project_id`,保持响应 Schema 与安全声明,记录原文和绑定子集摘要。
3. 实际调用 MCP `preview_contract_import`;首轮仅提交五项新增接口。后轮仅允许五项全部 unchanged,固定既有版本后重新生成资产。任何更新、删除或混合状态都阻断。
4. 对五个固定版本分别调用 `inspect_contract`、`generate_test_design`、`analyze_test_coverage`;核对所读版本,并比较同一策略/版本的覆盖结果。
5. 通过 MCP 建立 Context、生成 IntegrationPlan;H 只补显式合成数据和 typed `PlanBinding`,不手写执行图。
6. 登录输出的 access token 经已有 Header Mapping 传递;创建输出的 id 经已有 Extract/VARIABLE 机制绑定 PATCH/DELETE 路径。四个项目操作显式携带 B 的 `X-Organization-ID`。
7. 保持全部适用生成 Oracle,实际 MCP validate/compile/propose FlowSpec,再经公开审核、应用和版本发布 API 固定 Workflow。
8. 五份生成 Design 以显式 ID 映射纯组合,完整保留 Scenario、Oracle 和知识图;实际 MCP propose TestDesign/Case,经公开审核固定 Case 版本。

## 返回与采证边界

返回 `LifecycleAsset`,包括五项 `operations`、每份固定 `api_source`/Design/指纹、完整 IntegrationPlan、组合 Design/指纹/ID 映射、全部 Oracle 到 Assert 映射、审核固定的 Workflow/Case、实际 MCP 调用回执与生成/冻结时间。
`source_reused` 明确标记本轮是否复用了 unchanged 契约来源;每轮仍新生成 Design/Plan/Workflow/Case。
本轮文件写入传入的目录,包括绑定 OpenAPI、导入/读取/覆盖回执、Plan/编译结果、审核资产和最终生成资产。

根运行器应以 `asset.case.version` 和 A 目标 Environment 创建正式 TestPlan,使用既有引擎执行。
独立 Observer 必须核对全部五项 API 固定版本、真实执行和全部断言;B 的最终公开环境列表中 `created_resource_name` 与 `updated_resource_name` 均应不存在。
仅目录或资产生成成功不能标记执行成功。编译阻断、缺 Schema、缺版本、缺执行、缺后置条件证据均保留失败或不完整状态。

## 已做验证

[离线表征](../../backend/tests/test_selftest_generation_lifecycle.py) 使用候选应用真实 OpenAPI 验证五操作来源、响应 Schema、安全声明、隔离 namespace、全量生成 Oracle 保留、typed 路径绑定编译和 Design 组合。
该验证不等价于真实 MCP、A/B 执行、CI 合并门禁或真实宿主验收;实际运行结果由批次证据单独记录。
