# M10 契约中心整改记录

依据：[完整审计 M10](../../audits/2026-10-19/complete-audit.md#m10)、[修改方案 M10](../../audits/2026-10-19/remediation-plan.md#m10)。对应 `F-CT-01/02`。

**两项已实现，专项、完整本地检查及真实浏览器验收通过，计入39项本地完成。整合前一批Mock与手机摘要补修后的完整复验已通过；GitHub交付和正式环境验收独立确认。**

## 完整目录与审核上下文

- OpenAPI分析批次、候选审核与统一资产目录改为每页20项，显示服务端总数及当前页；批次按文档名搜索，候选按审核状态过滤，改变条件回到第1页。
- Provider、Pact与基线使用独立服务端搜索和分页，选中页外对象按ID补取。失败显示trace与重试，不替换为首项；未成功读取选中对象时禁止依赖它的提交。
- 批次/Pact元数据在数据库中按时间及ID稳定分页，同一SQL快照返回列表和total。Pact支持来源、消费者版本和服务名称搜索，通配符按字面处理，服务名有界批量读取。目录延迟加载原始文档，详情才读取指定文档。
- 审核批次独立按ID读取，目录翻页或搜索不清除选中批次；模态框与候选ID绑定，失败保留输入及trace，成功只关闭对应编辑器并刷新候选。读取权限成功后才能写入，提交时再次检查。
- 生成定义必须为JSON对象，数组/null/非法JSON在字段处拒绝。登记、导入及验证沿用真实Form提交与校验，空表单不产生未处理异常；上传文件列表受控。

## 冻结证据与只读合同

新增端点均位于 `/projects/{projectId}`：

| 读取                                       | 内容                                 |
| ------------------------------------------ | ------------------------------------ |
| `GET /contract-hub/pacts/{id}`             | 固定Pact元数据及解析文档             |
| `GET /contract-hub/verifications/{id}`     | 指定验证、其固定Pact及实际响应可用性 |
| `GET /contract-hub/deployment-checks/{id}` | 已保存发布判断及全部证据             |
| 既有 `GET /contract-runs/{id}`             | 固定分析批次、破坏性变更及基线ID     |

先检查功能开关与项目READ，再核对记录及引用服务归属；跨项目标准404及trace。Viewer可读取，已有写权限保持；没有模型变更及迁移。

兼容单元格、契约行和发布判断打开只读证据抽屉，显示全部blocker、待满足项、固定Interaction预期、验证状态和不匹配代码。OpenAPI显示每项变更的路径、基线值、固定当前值及基线详情，可返回上级证据；引用环不会无限扩展历史。原JSON放高级只读区。

既有验证只保存索引、描述、状态及不匹配代码，**没有采集实际响应**。界面明确“实际响应未采集”，不会把expected冒充actual，也没有扩大采集/日志政策。新Pact不替换旧验证预期。读取不触发验证、Broker/Provider请求、审计写入或草稿接受。

## 缺失数据与手机布局

- 分析失败、覆盖/差异缺失、目录失败与阻断列表未提供都明确标记，不能用0、100%或绿色成功替代未知。
- 覆盖率核对真实分母及有效百分比。分母0显示“无可评估项”，数据缺失或失败显示“未提供”，不渲染满进度条。
- 手机兼容区域和依赖图纵向排列，表格在自身范围横向滚动；浏览器发现的图最小列宽溢出已修复。
- 最后截图又发现摘要固定4列导致逐字换行。`cc93e93`改为手机1列、中屏2列、桌面4列；同一已接受用例只读补验确认5行摘要、状态文字高22px，视口与document均390px，没有通过裁切掩盖问题。

## 专项与完整本地检查

编辑前后端2模块9项、前端2文件15项基线通过。实现后3个后端具名模块12项通过：105条分页/搜索/字面通配符、审核过滤、Viewer读/写403、跨项目404、旧Pact冻结及只读无副作用；Provider/Broker被替换为立即失败，审计条数不变。

前端6文件26项通过：第101批次/候选、翻页保留、503保留输入并重试同一候选、页外对象精确读取失败及重试、3项阻断、旧Pact、JSON反例、空表单及缺失数据。格式、ESLint、TypeScript及构建通过。

源码 `3dbdca6cf7fcc0e204c17c755ca591fca7473ec3` 的backend树 `af4ff5a9d2e24be561c2bb9b017da59c603bfaeb`、frontend树 `012f4ab43bde0ad785733dd3437cd39f10f62aba` 完整检查通过：后端1846项、14跳过、2项既有警告、91.03%，Ruff格式/检查、mypy440文件通过；前端159文件1041项，无未处理异常，覆盖率85.88/82.14/85.42/88.31%，格式、lint/类型及构建通过。该树尚未包含Mock，不能冒充整合后用例数。

整合Mock及手机补修后源码 `cc93e93695a145fcaa9c4a2676109148217e1882`：backend树 `f222dd90d1277f84a0f60dbb9227058794319b1a`，frontend树 `9843d80a4f372915dde61f2d0f538ee8c0617590`。8项受影响测试、格式/ESLint和构建通过；一次校验提示刚进入DOM尚不可见的测试失败，已等待同一提示实际可见，保留断言，未提高超时或跳过。该精确整合树完整检查已结束通过：后端1877项、14跳过、2项既有警告、覆盖率91.06%，Ruff格式/检查与mypy442文件通过；前端161文件1063项、无未处理异常，覆盖率85.92/82.01/85.50/88.38%，格式、lint/类型和构建通过。完整检查期间应用与测试源码冻结。日志 `remediation-contract-cc93e93-backend-full.log`、`remediation-contract-cc93e93-frontend-full.log`。

同步已合并Mock原始JSON重复键补修后的源码 `a4e20689d74de0ebc201e27d44568ee6345fb6bc`，backend树仍为 `f222dd90d1277f84a0f60dbb9227058794319b1a`，与1877项完整检查完全一致；frontend树变为 `51b9e9c325cb19c7c3d2aaddeb35fec81c162e42`，已独立重新完成格式、lint/类型、162文件1070项测试及构建，无未处理异常，覆盖率85.94/82.05/85.50/88.40%。完整日志 `remediation-contract-a4e2068-frontend-full.log`。检查期间应用与测试源码冻结，未把旧树结果套用为新树结果。

## 真实 PostgreSQL 与浏览器验收

使用独立Compose `flowtest-product-completion`、端口13078及隔离Chromium，专用合成项目 `119ec67b-a137-4f60-8d8b-8b99af94adbd`。未修改用户3000端口或其他项目；重启backend/worker后readiness200。

1. 真实生成候选后注入一次审核503，保留编辑名称、说明及trace；恢复后真实接受同一候选ID，没有新建替代失败对象。
2. 创建21模块和2个Consumer，第21服务从第2页选为Provider；两次本地Provider验证构造明确失败记录，再导入新v2 Pact。查看旧记录仍是old-v1预期，actual明确未采集。
3. 发布判断3项blocker及待满足项逐项展开，检查固定验证/Pact、OpenAPI字段删除与准确基线，返回上级通过。**检查阶段契约写请求0、页面异常0**，不是声称构造样本阶段无HTTP请求。
4. 34条真实OpenAPI operation实际生成102候选。另在该合成项目数据库插入100条具名失败历史元数据，将真实批次放第101位；它们是分页fixture，没有伪造100次实际分析或执行。写前核对项目名称、唯一标记、102候选，提交前核对总数104及第101条ID。
5. 真实页面进入第6页第101批次/候选，批次翻回首页仍编辑原候选。一次审核同一ID为accepted，pending从102变101，accepted筛选1条；独立基线搜索仍能选择页外原批次。契约命令恰好1次、页面异常0。
6. 桌面1440/document1440、手机390/document390。抽屉等待实际进入视口后补截，宽390、正文scrollWidth390，可滚动检查全部证据；早先过早截到背景的图片未算布局证据。摘要补修后同一批次及已接受候选只读复验，契约命令0。

忽略目录日志：`remediation-contract-review-browser-r3.log`、`remediation-contract-evidence-seed.log`、`remediation-contract-evidence-browser-verified.log`、`remediation-contract-deep-api-seed.log`、`remediation-contract-deep-catalog-seed.log`、`remediation-contract-deep-browser.log`、`remediation-contract-mobile-drawer-position-verified.log`、`remediation-contract-responsive-summary-browser.log`。最终图已逐张目视复查；摘要为 `remediation-contract-responsive-summary-mobile-verified.png`，抽屉为 `remediation-contract-mobile-drawer-position-verified.png`。

## 改动与尚未验收范围

- 后端：[批次仓储](../../../../../backend/app/repositories/contracts.py)、[Pact仓储](../../../../../backend/app/repositories/contract_hub.py)、[服务及授权](../../../../../backend/app/services/contract_hub.py)、[只读端点](../../../../../backend/app/api/v1/endpoints/contract_hub.py)、[回归](../../../../../backend/tests/test_contract_catalog_evidence.py)。
- 前端：[批次审核](../../../../../frontend/src/features/contracts/ContractAutomationPanel.tsx)、[独立选择](../../../../../frontend/src/features/contracts/ContractReferencePicker.tsx)、[冻结证据](../../../../../frontend/src/features/contracts/ContractEvidenceDrawer.tsx)、[契约中心](../../../../../frontend/src/pages/ContractHubPage.tsx)、[样式](../../../../../frontend/src/styles.css)，及相关SDK和具名测试。
- 尚需本批最新HEAD正式Required Gate与审查、GitHub合并及合并后回归。S18/S27正向流程保留，未凭猜测改定位/超时/跳过；完整Compose验收由本批PR独立确认。
- 未访问真实外部Broker/Provider，未做正式部署及真实Windows终端运行；本批不代表全站设计签收。

## PR143正式验收补修

旧HEAD `2475a75166fa8173bebdef5c30a63a699b46e18e` 的正式运行39542617128结束失败：Compose浏览器66项通过、仅S27失败，其余原门禁作业通过。首次全局同名文字定位误点弹窗后背景Provider；重试又在导入弹窗未关闭时匹配两个提供方下拉框。`d49111d2cddddba2370ef305084477687f2e7c1b` 将三处引用选择限定为当前展开选项，等待OpenAPI弹窗隐藏后操作兼容矩阵，版本输入按真实标签定位，保留原180秒上限、重试规则和全部业务断言。

真实浏览器又复现先验证再导入时两张保留表单共用provider_version ID，导致可见标签指向隐藏输入。新增顺序回归修复前1失败，两个Form添加独立名称后，点击当前标签正确聚焦当前输入。测试使用关闭动画及重新读取当前输入节点，未移除可见性/值断言。3个具名前端文件22项通过，格式/ESLint/类型、构建及既有S27用例发现检查通过。

源码d49111d的frontend树 `92ad3e044604d3d9890adb8859991dadae5187b5` 独立完整检查通过：162文件1071项、无未处理异常，覆盖率85.97/82.05/85.56/88.44%，格式/lint/类型/构建通过。backend树 `f222dd90d1277f84a0f60dbb9227058794319b1a` 未变，仍对应1877项/91.06%的完整通过。日志 `remediation-contract-provider-label-frontend-full.log`；旧失败与复现日志分别保留。

专用项目 `11582acc-199f-4961-8ca9-3ecd678762b9` 真实Pact导入及本地Provider验证201后，继续OpenAPI绑定、兼容矩阵通过、发布判断safe和两类资产切换，页面异常0。另按先验证弹窗再OpenAPI的顺序做只读检查，两个输入ID不同、点击标签聚焦正确，命令0、异常0；日志 `remediation-contract-s27-browser-followup-resume.log`、`remediation-contract-label-focus-browser.log`。补验分阶段继续同一专用样本，没有重复提交失败阶段的已完成命令，也没有访问外部Provider/Broker。

当前39项本地完成、34项待完成、37项已合并；本批新HEAD正式门禁、合并及合并后回归另行确认。Mock合并后Full Regression39541655090已结束成功，精确head为df1d481330b8d063ea0b18f5397d089fa6de4964；不会将该main结果替代本PR的新门禁。
