# ADR 0011：测试资产不可变版本与计划目标快照

状态：Accepted

## 背景

V1 Test Plan 只能直接引用 Workflow。团队复用测试场景时需要可独立检索、克隆和组合的 Test Case / Test Suite，同时历史计划运行不能因资产草稿或子项后续发布而漂移。

## 决策

1. Test Case 与 Test Suite 都保留一个可修改草稿；每次发布创建只增不改的版本及内容指纹。
2. Case Version 固定 Workflow Version、Environment 和运行覆盖；Suite Version 固定每个 Case Version，发布时拒绝未发布、重复或跨项目引用。
3. Test Plan Item 使用 `target_type/target_id/target_version` 表示 Workflow、Case 或 Suite，同时保留 V1 Workflow 字段作为兼容读取面。
4. 计划创建时解析并固定目标版本；计划入队时将 Suite 展开为 Case Run Item，并为每项保存 `target_snapshot`。执行只消费该快照，不回读最新草稿。
5. 版本 Diff 是结构化字段变更列表，不把展示文本作为执行事实。发布版本不提供更新或删除接口。

## 结果

- 草稿修改、Case 重新发布或 Suite 成员变化不会改变已有计划和运行历史。
- V1 `workflow_id/environment_id` 请求继续有效，升级不要求重建现有计划。
- 回滚到 0011 无法表达 Case/Suite 计划项，因此必须先备份；迁移会删除非 Workflow 计划项和全部测试资产。
