# 第八批：请求目标任务化、只读候选解析与确认保存

依据：[M04 详细方案](../../audits/2026-10-19/remediation-plan.md#m04)。本批包含 `F-TGT-01`、`F-TGT-02`、`F-TGT-03`，实施日期2026-10-21。

## 当前完成边界

`F-TGT-01` 已实现并通过本地专项、类型、构建及1280/390px真实浏览器验收。`F-TGT-02`、`F-TGT-03` 已具备只读解析、版本和上下文隔离、候选确认及取消保护，但**本次绑定候选的下游影响范围仍在完善，不计为全部完成**。已有服务静态引用不能代替一次接口绑定或环境默认服务变更的真实影响范围。

## 已实现的页面任务链

桌面先显示逻辑服务目录，再读取所选服务在当前环境中的部署地址；新建表单收进“新建逻辑服务”，不占据目录首屏。手机显示服务选择器和当前服务编辑入口，隐藏技术目录表格。每个地址变体显示地址、状态和修订；连接超时、TLS、代理、请求头、变量、凭据引用和健康检查进入分组详情。

接口默认服务以项目目录分页卡片展示，手机不再横向挤压多列表格。页面说明节点服务覆盖、接口绑定、环境默认服务的解析关系。选择目录中的服务仅改变查看对象，不写入默认绑定。

请求头和变量复用已有类型约束的键值编辑器，保留高级JSON入口。表单校验后才构造字符串映射，未展开的字段不会丢失。已有但不再可选的凭据引用保留并明确标注，不自动删除或替换。连通性检查保留独立按钮，保存和解析不会自动探测目标。

实现入口：[RequestTargetsPage.tsx](../../../../../frontend/src/pages/RequestTargetsPage.tsx)、[EnvironmentEndpointCard.tsx](../../../../../frontend/src/features/service-targets/EnvironmentEndpointCard.tsx)、[TargetChangeComparison.tsx](../../../../../frontend/src/features/service-targets/TargetChangeComparison.tsx)。

## 只读解析合同

新增受项目读取权限保护的 `POST /projects/{project_id}/request-targets/preview`。环境、接口、可选固定接口版本、节点服务覆盖及地址变体组成预览上下文；候选类型为逻辑服务启停、地址路由字段、环境默认服务或接口默认绑定。

候选使用独立的未附着数据库会话的模型值，复用 `RequestTargetResolver` 的优先级、模板变量、导入网关路径及查询参数序列化。预览不提交、不改动已加载的持久化模型、不查询或解密Secret，不调用DNS或目标HTTP。响应只包含地址、服务标识、变体、地址修订、接口版本和带trace ID的不可用原因，不返回请求头、请求体、认证或变量全集。

缺少环境/接口上下文、运行变量、认证查询参数或服务地址时明确显示无法完整计算；显式服务/变体失败不回退。跨项目、未知或已归档上下文拒绝读取。环境默认服务候选必须存在default地址；地址变体重命名冲突拒绝预览。URL中的用户凭据不作为可展示目标。

接口绑定沿用现有保存合同：显式保存会新增接口版本，即使绑定值相同也会新增版本。预览显示同样的新版本号；选择固定历史接口版本时保持原绑定。预览只计算地址，不宣称已验证认证、请求头、请求体、业务结果或出站可达性。

实现入口：[target_preview.py](../../../../../backend/app/domain/target_preview.py)、[target_preview.py](../../../../../backend/app/schemas/target_preview.py)、[target_preview.py](../../../../../backend/app/services/target_preview.py)、[HTTP路由](../../../../../backend/app/api/v1/endpoints/service_targets.py)、[TargetResolutionPreview.tsx](../../../../../frontend/src/features/service-targets/TargetResolutionPreview.tsx)。没有数据库结构变更。

## 候选、确认与异步隔离

环境默认服务和接口绑定的下拉只生成本地候选。服务和地址编辑先校验、锁定候选并展示字段对比，再显式确认保存；返回修改会重新分析。服务器当前生效值与候选分别展示。保存失败保留候选，可以重试；取消不写服务器。

环境候选保存使用打开时捕获的环境对象，接口候选使用捕获的接口ID。环境消失或权限撤销后禁用确认；地址保存额外核对原环境。旧环境的影响查询迟到时不会打开编辑器，旧会话的保存结果不关闭新会话。新建地址成功也不会重置其他环境的新输入。

离页保护接入已有 `DraftSessionProvider`，没有第二个路由blocker。取消导航保留输入；明确“放弃候选并切换”才离开。刷新/关闭浏览器受未保存提示保护。其他模块的会话草稿继续保留。未修改的单纯查看不标记为脏草稿。

实现入口：[BindingReviewModal.tsx](../../../../../frontend/src/features/service-targets/BindingReviewModal.tsx)、[TargetDraftGuard.tsx](../../../../../frontend/src/features/service-targets/TargetDraftGuard.tsx)、[DraftSessionProvider.tsx](../../../../../frontend/src/features/drafts/DraftSessionProvider.tsx)。

## 复审补修：内联节点、发布版本

服务影响查询原先只扫描主图。新增公开HTTP用例先复现步骤组内请求遗漏，再补齐平铺regions。继续复审发现新版 `http.request@2.0.0` 的配置位于configuration，已按执行引擎的类型映射识别，并排除非HTTP节点。版本绑定和节点服务覆盖均有回归。

发布流程原先只固定主图的API版本，内联区缺少api_version时会继续跟随接口新版。新增两类节点的公开创建/发布用例，先复现发布后版本仍为空，再将固定版本步骤应用到主图及所有regions。只影响新发布版本，不改写历史已发布版本，也不把固定版本写回用户草稿。历史数据若保留未固定引用，后续候选影响分析必须按其实际内容识别，不能假定所有历史流程均已固定。

实现入口：[service_targets.py](../../../../../backend/app/services/service_targets.py)、[workflows.py](../../../../../backend/app/services/workflows.py)。

## 已运行的验证

| 验证                       | 实际结果与限制                                                                                                                                                                                                                                                                                                                                                   |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 完整make check             | 源码提交 `2a62fb504ff5f42a6e8fc09e90cb5457ad514891` 全部通过：后端1788项、13跳过、2项既有警告、覆盖率90.87%；前端147文件949项，无未处理异常，覆盖率85.69% / 81.77% / 85.13% / 88.19%。包含格式、Ruff、mypy、lint、类型及生产构建。后端树 `5a5497e4c96e655398e63ca54299f1e3132d1d89`，前端树 `763c8d0b63543357472ba0e206ab21ec369de7cd`。后续补修仍需新提交验证。 |
| 新版HTTP引用与版本预测补修 | 后端4个具名文件54项通过；新版节点遗漏和相同绑定版本号均有修复前失败、修复后通过记录。                                                                                                                                                                                                                                                                            |
| 内联发布固定版本           | 3个具名后端文件50项通过，覆盖两类区域HTTP节点、发布后接口升级、历史指纹及草稿保持。mypy434文件、相关Ruff通过。                                                                                                                                                                                                                                                   |
| 候选及草稿交互             | 6个具名前端文件37项通过，含相邻对象工作区/流程保存并发；增加服务目录选择后，3文件14项通过。覆盖取消无写入、失败原候选重试、权限撤销、环境失效、迟到影响响应、迟到解析响应、分页与搜索、固定版本/变体输入、统一导航保护。                                                                                                                                         |
| 最终页面专项               | 桌面1280与手机390已查看截图。手机文档宽375、服务选择器显示、技术表格隐藏；桌面相反。高级键值/JSON与未展开字段往返保存通过。后续页面构建成功；一次构建发现测试查询类型错误，修正后重新通过，没有放宽规则。                                                                                                                                                        |

完整日志位于 `output/playwright/audit-20261019/`：`remediation-request-targets-make-check-r1.log`、`remediation-target-final-targeted-backend.log`、`remediation-target-region-publish-before-r2.log`、`remediation-target-region-publish-after.log`、`remediation-target-frontend-r11.log`、`remediation-target-frontend-r13.log`、`remediation-target-build-r5.log`。最早的区域测试先因缺少预算、发布测试先因测试开关未启用而拒绝；补齐有效上下文后才记录真正的行为失败，没有改产品默认开关。

## 真实PostgreSQL与浏览器验收

使用既有独立审计栈，新增“请求目标候选审计20261021”合成环境及订单、结算两个逻辑服务；结算配置default/canary两个地址。没有改动既有流程草稿或业务数据。预览将结算地址从原v2路径计算到候选路径，取消后读取数据库仍是原URL、修订1，环境默认服务保持原值。

对独立合成接口显式确认绑定后，当前版本为v2；实际API预览与候选地址一致，v1仍使用原环境地址。没有运行该接口或执行目标连通性检查。证据：`remediation-target-cancel-postcondition.log`、`remediation-target-binding-postcondition.log`。截图：`remediation-targets-final-mobile.png`、`remediation-targets-final-desktop.png`、`remediation-target-preview-mobile-r2.png`。

本地静态服务曾命中旧HTML缓存；已比对磁盘/HTTP脚本与浏览器实际脚本，使用明确的previewBuild查询进入新构建后才验收新版手机目录。此记录不代表生产部署缓存策略已经验收。

## 继续实施的精确范围

1. 现有服务静态引用已接回ID、名称、原因、对象链接及真实分页范围，但不能当作本次候选的精确影响。尤其是新绑定服务尚无既有引用时，不能用其静态零条推断变更不影响流程。
2. 补齐候选范围计算：区分当前版本引用与固定API版本；处理主图、regions、新版HTTP、固定子流程引用，以及用例/套件/测试计划的实际版本与环境来源。
3. 无法解析的历史引用、缺失对象和扫描边界明确列诊断；没有完整枚举时显示已识别数量及缺项，不能显示为确定的零影响。发布策略仍需区分潜在证据关系与实际门禁结论。
4. 将本次候选的结果放到确认保存步骤，与同一候选、环境、版本的URL结果一致。完成公开行为回归、最终完整检查和最新提交远端门禁后，才能将F-TGT-02/03标记完成。
