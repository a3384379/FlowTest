# 第八批：请求目标任务化、只读候选解析与确认保存

依据：[M04 详细方案](../../audits/2026-10-19/remediation-plan.md#m04)。本批包含 `F-TGT-01`、`F-TGT-02`、`F-TGT-03`，实施日期2026-10-21。

## 当前完成边界

`F-TGT-01`、`F-TGT-02`、`F-TGT-03` 均已实现，并通过本地专项、完整检查及真实PostgreSQL/浏览器验收。完整检查与后续补修的源码边界分别列在文末。当前共30项本地完成、43项待完成，其中27项已合并；本批PR #139仍须最新HEAD正式门禁和审查通过后合并。不代表全站设计签收或正式发布验收。

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

## 候选专属依赖分析

新增只读 `POST /projects/{project_id}/request-targets/impact-preview`，仅接收冻结候选，不接收单个URL预览上下文。用户修改接口版本、节点覆盖和Variant时只重新计算URL，不反复扫描项目。与URL预览均完成当前候选的读取后才允许确认；失败可显式重试，迟到的旧候选结果不进入新候选。确认步骤移除旧/新服务的静态计数，改用此次候选的依赖结果。

分析遵循真实引用：接口绑定新增当前版本，只影响未固定API版本的节点；历史固定版本不随绑定变更。地址变体识别原值与重命名候选，按节点覆盖、接口绑定及环境默认顺序匹配。流程包含主图、regions、原生HTTP capability、固定传统子流程和结构化workflow_ref。计划按固定工作流版本与环境计算；用例按已发布定义、套件按已发布成员版本展开，不读取当前草稿来替代固定来源。定时配置包含禁用状态标识。发布策略仅列可能使用这些计划新运行的策略，不计算或伪造发布判断。

通过类型接口注入只读元数据仓储。查询全部限制在当前项目；接口版本仅取服务绑定列，不加载请求体、认证、请求头等大字段；环境不加载变量，地址不加载凭据，计划不加载webhook材料。流程/用例JSON先读ID和长度，再按每类500个、单定义100000字符、累计1000000字符读取；其他元数据按类别上限2000/20000条。分析最多10000个节点、100000次比较、32层固定引用。超过边界、无效/缺失引用或循环都返回明确诊断、`complete=false`和trace ID，页面显示“已识别”数量，不冒充精确零影响。已归档/不可用的目录项不会提供错误跳转。

服务/环境候选显示跨版本潜在引用；计划结果进一步绑定实际执行环境。这些结果不能声明每项业务行为一定改变，也不改写历史执行快照。候选没有新增数据库模型、迁移、目标探测、自动运行、日志或捕获开关。

实现：[类型合同](../../../../../backend/app/domain/target_dependencies.py)、[有界仓储](../../../../../backend/app/repositories/target_dependencies.py)、[分析服务](../../../../../backend/app/services/target_dependencies.py)。公开行为回归：[HTTP](../../../../../backend/tests/test_target_dependency_api.py)、[分析合同](../../../../../backend/tests/test_target_dependencies.py)、[前端候选交互](../../../../../frontend/src/features/service-targets/TargetResolutionPreview.test.tsx)。

## 合并后回归追查：服务目录加载

PR #138主分支的Full Regression 39466805365最终失败：前端940通过、2失败（服务目录长场景超时及页外选中搜索没有更新）；其余已执行作业与原PR门禁不能替代该失败。补充交互断言复现搜索时Card骨架屏卸载搜索框。现改为仅表格loading，搜索保持挂载；测试等候真实匹配结果而非“旧行消失”这个可能由加载态满足的条件，并将登记与搜索拆成独立任务。未放宽超时、覆盖率、检查或接口行为。

修复提交 `163d61b`：新增搜索框稳定断言修复前失败，修复后7项通过。完整回归仍待本批当前提交验证，不能以专项通过宣称主分支旧运行成功。

## 当前验证补充

- 当前候选范围：六个具名后端文件83项通过；覆盖只读权限、跨项目、固定版本、历史未固定引用、子流程、用例/套件/计划环境、105条引用、JSON上限与诊断。日志`remediation-target-impact-backend-r4.log`。
- 前端三个文件16项通过；依赖查询与URL输入分离、分页、归档入口、失败重试、未完整数量和迟到结果隔离。日志`remediation-target-impact-frontend-r3.log`。
- 新代码Ruff/mypy437文件、前端lint/TypeScript及生产构建通过。复杂度检查先发现两个组件超过上限，拆成专门的结果及诊断渲染组件后通过，没有降低检查。
- `c4be1b168825940130ac154bd58c60862ee37e9f`完整make check通过：后端1819项、13跳过、2项既有警告、90.94%；前端147文件952项，无未处理异常，覆盖率85.68% / 81.82% / 85.12% / 88.19%，格式/类型/lint/构建通过。日志`remediation-request-targets-make-check-r2.log`；后端树`1674924a19c4471b84c6989d1c9d5320351f4ef1`，前端树`8f4c28b05848b7bcad7be752aa08ffe57ca8d7bd`。
- 继续审计发现套件展开未受全局比较预算约束。公开分析合同先复现100个无效用例在预算5时仍全展开；将计划成员与套件成员计入同一预算并将环境默认服务匹配预索引，防止乘积扫描。修复前失败、修复后两个文件28项通过。补修后的完整后端Ruff/格式/mypy437文件/pytest通过：1820项、13跳过、2项既有警告、90.96%，后端树`94dba6b4f2ffb6f7750a8c12cb5e8f55edd69b93`。日志`remediation-target-suite-budget-before.log`、`remediation-target-suite-budget-after.log`、`remediation-target-suite-budget-backend-full.log`。
- 真实手机发现长内容将操作区推至屏幕之外。提交`0904dee8b3183f27e3c7e2241ea9091c5507eb1c`将两类确认弹窗居中，并限定内容滚动。手机390×926时保存按钮由y=2209移至y=840，弹窗y=30、高866，文档宽390；桌面1280×926也保持操作可见。更新后4个具名前端文件23项、格式、lint/TypeScript及构建通过；未重复宣称布局补修后的本机全量前端覆盖率已运行，最新HEAD的远端完整检查独立确认。前端树`1e5c441457db48fa7f34d4734f602d9d6eeb71d7`。
- 最新真实浏览器依赖验收新增独立合成流程`c979d7ad-89bc-4e97-bc9c-7936489cd258`和禁用计划`abba866a-e958-48b9-b941-28ff13495e65`。地址候选识别草稿/发布v1、固定计划和禁用定时；接口绑定候选只识别草稿，固定计划排除。结果完整、诊断空，没有执行目标。证据`remediation-target-live-dependencies.log`；最新版截图`remediation-target-modal-final-desktop.png`、`remediation-target-modal-final-mobile.png`。最早弹窗截图仅是发现布局问题的证据，不能当作最终效果。

## 审查补修：接口绑定确认的版本基线

PR #139审查指出，预览后另一编辑者发布接口版本时，原绑定保存会复制确认时的新当前版本。公开HTTP回归先因旧预览合同不接受新令牌而返回422；改用既有预览请求后，真正复现旧候选被接受并生成未审阅v3、连带改写名称。未将最早的合同拒绝当作行为复现。

补修提交`f45e698a3d7c99c1fd8ad42685a63c4d195deae1`：接口候选的URL解析、依赖分析和最终PATCH均带同一`base_version`。服务端在原行锁内验证当前版本，和既有版本发布共用API记录锁；检查先于名称、分组、绑定、版本及审计写入。版本不符返回标准409/API_VERSION_CONFLICT和trace ID，不自动采用其他编辑者的修改。令牌绑定被修改的API，不取用户另选URL预览接口或固定历史版本的版本号。可选字段保持既有API调用兼容，无数据库迁移。

页面显示锁定版本；冲突保留候选并禁用确认，显式“读取最新版本并重新分析”才读取最新定义、保留服务选择、重新开始解析。取消后的迟到读取不改写或关闭新会话。该测试另复现未绑定接口的Select以undefined运行时会在取消后残留候选；接口与环境默认绑定现使用受控null，取消后继续显示服务器值。

已验证：六个相关后端文件86项通过；四个前端文件24项通过；Ruff及两处修改服务的显式C901检查、mypy437文件、lint/类型及构建通过。真实PostgreSQL三项并发测试通过：同基线的绑定和发布仅一方成功，另一方409，最终只存在v1/v2，并核对胜方路径和原v1不变。测试运行镜像原无pytest-asyncio/pytest-cov，最初运行只在工具层失败；随后仅在临时测试目录准备项目锁定的pytest-asyncio1.4.0及其元数据，使用镜像原pytest9.1.1执行，没有改产品依赖或启用覆盖率收集。最终日志`remediation-target-binding-postgres-concurrency-r4.log`。其他证据：`remediation-target-binding-version-before-r2.log`、`remediation-target-version-final-backend-targeted.log`、`remediation-target-binding-ui-version-after-r4.log`。

本次补修`f45e698`完整make check全部通过：后端1822项、14跳过、2项既有警告、覆盖率90.95%；前端147文件954项、无未处理异常，覆盖率85.68% / 81.81% / 85.12% / 88.18%，格式/类型/lint/构建通过。日志`remediation-request-targets-make-check-r3.log`。后端树`17ccbfa3d6cea48e7ec9357cff2443e05a38b068`，前端树`bba7a0ad3538610e106633ebaf772027034ba48e`。其后仅补手机版式，将版本提示的刷新按钮移到说明下方，防止文字被横向挤窄；当前HEAD远端门禁独立确认。

真实浏览器并发链路：合成接口预览基线v2后，另一个请求发布v3（新路径`/health/parallel-review`，仍绑定结算服务）；旧候选确认返回409并显示trace，确认按钮禁用，PG读取保持v3且未生成额外版本。显式读取最新版本后显示v3、新路径和同一服务选择；确认保存为v4后，真实API预览与新候选相同。v1、v2、v3的路径与绑定保持，原已发布流程仍固定APIv2。证据`remediation-target-version-live-publication.log`、`remediation-target-version-live-conflict-postcondition.log`、`remediation-target-version-live-save-postcondition.log`。只操作独立审计合成数据，没有发起目标执行。

最后的版本提示纵向布局仅改变说明/按钮排版，四个具名前端文件24项、lint/TypeScript及构建通过。390×926截图已复核：版本说明保持正常行宽、刷新位于说明下方，保存/取消保持可见，文档宽390；截图`remediation-target-version-notice-final-mobile.png`，几何记录`remediation-target-version-notice-mobile-geometry.log`。此验收候选只打开后取消，没有在v4后增加API版本。该小版式调整后的本机全量覆盖率未重复运行；f45全量结果与最新HEAD远端全量门禁分开记录。

### 远端完整前端回归的超时修正

`9798cdea45b492988fcd63e96494ba633f8e21e4` 的 PR Validation [39481664884](https://github.com/a3384379/FlowTest/actions/runs/39481664884) 未通过：服务目录综合测试超过既有60秒上限，其他953项前端测试通过；其余后端、Compose、Windows与升级作业通过。这不是合并成功。

将该测试拆为目录证据/旧链接定位和服务端搜索两个独立场景，限定目录与详情的DOM查询范围。搜索和清空均等待服务端返回的匹配总数实际进入页面，再校验选中ID仍固定；恢复对清空后结果的正向断言。保持原有超时、覆盖率和CI标准。修正后的8项服务目录测试本地通过，日志`remediation-service-ci-timeout-targeted-r1.log`。最新HEAD的远端门禁仍需独立确认，不能把本地通过替代远端结果。

### 最终交付回执

已核对最终HEAD `d90db72b1d2b7e2da4161a23ba4a6e1110655d2b` 的正式Required Gate成功（[PR Validation 39489056918](https://github.com/a3384379/FlowTest/actions/runs/39489056918)），所有审查线程已解决、无后续分页。使用匹配该SHA的合并命令，PR #139于2026-10-20 20:46:59 UTC合并到main，提交`722d72f196d58b5f1693dd15a0daa474faa8fd0e`。

合并后已启动[Full Regression 39494968109](https://github.com/a3384379/FlowTest/actions/runs/39494968109)，确认运行head为上述main合并提交；当前等待其结果。PR门禁成功与合并后回归分开记录，不将旧失败运行或尚未完成的回归记为成功。
