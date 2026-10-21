# M09 数据与 Mock 整改记录

依据：[完整审计 M09](../../audits/2026-10-19/complete-audit.md#m09)、[修改方案 M09](../../audits/2026-10-19/remediation-plan.md#m09)。对应 `F-DATA-01/02`。

**当前状态：两项已实现并完成本地验证。功能、桌面与手机布局、真实Mock对照、Unicode预算补验及最终完整本地检查通过。已计入37项本地完成；GitHub交付及合并后验收独立记录。**

## 已实现行为

- 选择已保存规则可查看和编辑。修改沿用既有 `PUT /projects/{projectId}/mock-services/{serviceId}/routes/{routeId}`，保留路由ID；方案写作PATCH与实际合同不符，本次沿用真实PUT处理链。
- 列表增加场景、优先级、启停。停用只影响后续匹配；已有未保存输入时保护草稿，切换规则或服务需明确选择继续编辑或放弃并切换。
- 名称、说明通过既有服务PATCH维护，slug只读，既有访问地址保持。保存失败保留字段并显示trace；目录刷新失败保留输入且禁用依赖该目录的写操作。
- Query条件、Header条件及响应头使用键值行，保留高级JSON入口。必须为字符串值的JSON对象，数组、数字、null及重复键在字段处报错；Header键名不区分大小写。
- 响应体支持JSON值或文本字符串。实际Mock通过JSON响应返回，文本模式保存JSON字符串值；没有冒充原始text/plain响应。响应Header按字面返回。
- Viewer可以检查规则，单独填写合成请求并预览；规则字段和保存、启停、删除保持只读。

## 新增只读预览合同

`POST /projects/{projectId}/mock-services/{serviceId}/routes/preview` 读取项目与服务，不执行Mock dispatch。

| 内容     | 合同                                                                                                 |
| -------- | ---------------------------------------------------------------------------------------------------- |
| 输入     | 闭合draft、可选现有route_id、合成请求method/path/query/headers/body                                  |
| 授权     | 项目READ；校验项目、服务和既有路由归属                                                               |
| 输出     | 服务状态、草稿条件逐项结果、实际命中规则及草稿身份、场景、优先级、延迟、响应及字段提示               |
| 副作用   | 不保存，不写审计或请求日志，不发外部请求，不执行延迟，不解释脚本                                     |
| 路径     | 表示应用收到的已解码路径，不替用户规范化尾斜杠或重新URL解码                                          |
| 场景     | Query `_scenario` 优先，其次 `X-FlowTest-Scenario`，与实际dispatch同一选择函数                       |
| 匹配顺序 | 场景必须完全相同；优先级降序、创建时间升序；编辑保留创建时间，新草稿同优先级排在已有规则之后         |
| 模板     | 复用已有模板渲染器；完整变量保留JSON类型，字符串插值仅支持标量                                       |
| 模板错误 | 字段、JSON Pointer、相关规则ID、标准错误信封和trace；未知/不完整语法按既有运行语义保留字面文本并提示 |

草稿满足条件但被已有高优先级/较早规则覆盖时，也验证其模板，避免新草稿错误被覆盖而没有反馈。结果仍标识真实命中的已保存规则，不能将草稿响应冒充实际结果。

## 不可信输入与状态归属

- 单个模板或合成请求体64KiB、深度32、节点4096；规则候选最多500，目录元数据512KiB。仓储先检查数量/元数据体积，再有界读取；候选响应体延迟加载，只读取实际命中的已保存模板。SQL字符预检为UTF-8预算的6倍，以兼容数据库JSON的Unicode转义；有界读取后领域层仍按实际UTF-8严格校验，不扩大对外预算。
- 输出限制为安装配置的响应上限，默认2MiB；深度64、节点8192、最多20条模板提示。插值展开前估算字符串字节预算，完整对象引用再经过有界JSON遍历。超限明确失败，不截断目录或返回局部结果。
- 预览按提交前输入代次归属；修改草稿、合成请求、权限、规则、服务状态或目录读版本时清除旧结果。旧成功和旧错误都不能覆盖新上下文。
- 服务端JSON Pointer只显示为文本；表单错误定位只使用闭合字段枚举，不把未知对象键或指针交给动态Form路径。
- 不改执行引擎、工作流环境合同、Credential秘密边界、默认脱敏状态及日志采集策略；无数据库模型变更和迁移。

## 专项验证与源码边界

功能源码提交 `72fb468982e9d15e3bfb50ee84fab8c369f23ab9`，backend树 `5e286d56ba98a31e62f80f9face5d7dd693e0066`，frontend树 `a75cbaa69c9a0b7cb46ed868ed50edb548a49f96`。

- 59个后端定向用例通过：预览与真实Mock对照、同路由启停/后备、真实创建顺序、Query/Header场景优先关系、Viewer读取与写入403、跨范围拒绝、模板字段及指针、标准trace、无审计/请求日志写入、输入/输出/目录预算，另含已保存中文模板与目录元数据的真实UTF-8预算。
- 30个前端定向用例通过：规则维护、结构化配置、文本合同、非法Header类型、只读预览、字段定位、失败保留输入、服务编辑、切服务保护、目录失败禁写，以及五种上下文变化后的迟到成功/错误。
- 相关Ruff、mypy、Prettier、ESLint、TypeScript和生产构建通过。完整backend/frontend检查另行记录终态，不以专项通过代替完整门禁。

相关测试：[后端API](../../../../../backend/tests/test_mock_preview.py)、[领域语义](../../../../../backend/tests/test_mock_preview_domain.py)、[规则工作区](../../../../../frontend/src/features/data-sources/MockRouteWorkspace.test.tsx)、[表单与预览](../../../../../frontend/src/features/data-sources/MockRouteForm.test.tsx)、[数据与Mock页面](../../../../../frontend/src/pages/DataMockPage.test.tsx)。

## 真实浏览器验收

在独立Compose项目与隔离Chromium会话中，使用专用合成项目 `5d092f99-bcda-4552-a384-0fb227933cfb`。八个服务运行且健康，readiness HTTP200；重启backend/worker以加载新增只读API。没有修改真实业务数据或真实秘密。

1. 真实编辑同一路由ID、优先级42及JSON模板；键值行填写Query/Header，合成POST请求；预览201与实际Mock201的JSON完全一致，数组类型保留。
2. 未定义变量返回422、response_body字段、`/nested/0`指针及trace；编辑后旧结果清除。
3. 草稿停用后预览命中已保存后备规则202；保存同一路由ID为停用后，实际Mock也返回202；再重新启用主规则。
4. 服务保存注入单次合成503后字段保留并展示trace，恢复真实PATCH保存名称和说明，slug保持；实际模态框名称可访问。切服务先继续编辑保持草稿，再放弃并切换，另一服务没有旧输入。
5. 初轮截图发现桌面编辑区过窄、纵向过长，随后补修目录位置与并排布局；最终显式核对1440px和390px视口，document分别1440、390，无横向溢出，正向流程页面异常0。
6. 使用S17相同的具名表单定位，真实UI新建服务、创建规则、实际Mock访问和请求日志检查通过。新增规则和预览入口使旧的整页“新建”、部分“路径”标签定位产生歧义，已将E2E定位限定在各自表单并使用完整标签，没有放宽断言、增加超时或跳过测试。完整S17仍需本批GitHub Compose门禁确认。
7. PostgreSQL实测发现60002字节、20000个中文字符的已保存模板被数据库转义字符数误判为超限；补修后，同一服务和同一路由只读复验返回200、20000字符且响应完全相同。没有重复创建替代样本，也没有扩大源预算。

忽略目录证据：`remediation-mock-browser-r2.log`、`remediation-mock-browser-fallback.log`、`remediation-mock-service-browser.log`、`remediation-mock-create-legacy-browser.log`、`remediation-mock-unicode-budget-before.log`、`remediation-mock-unicode-budget-after.log`。最终布局截图及尺寸证据见下节。最初脚本的相对URL和隐藏ARIA选项定位错误均保留失败记录，修正定位后完整复跑，不计作产品验收通过。

## 尚未完成

- 当前HEAD的GitHub正式Required Gate、审查、合并和合并后回归。
- 其他尚未整改模块仍按R2→R3→R4逐一推进；本批不表示73项整改全部完成。

## 布局补修与最终复验

第一轮功能源码72fb468的完整本地检查结束：后端1872项通过、14项跳过、2项既有警告，覆盖率91.06%；Ruff格式/检查及mypy442文件通过。前端159文件1056用例通过，无未处理错误，覆盖率85.94/82.01/85.52/88.41%，格式、lint/类型和生产构建通过。

真实截图复查后，将规则目录移到编辑器之前，桌面配置与合成预览并排，手机按顺序堆叠。使用原生Grid减少布局层级；预览默认展开。Grid最初把800px表格的最小内容宽带到手机，实际浏览器发现后补上有界轨道与子项最小宽度约束，未通过裁切隐藏内容掩盖溢出。

布局测试曾因整页按角色扫描而在JSDOM样式继承计算中超时；性能采样和测试任务定位后，改为按已有可访问标签进入规则、在对应表单内定位保存按钮，并在目录刷新前捕获待检查控件。保留失败输入和禁写断言，另断言同一控件仍在文档中；未增加超时或跳过测试。具名反例约0.8秒通过，整个3文件30用例通过。

布局补修源码 `e4b1165e8121c1ec788dfbe5e371d43853f105d6` 的完整检查已通过：后端1872项通过、14项跳过、2项既有警告，覆盖率91.06%，Ruff格式/检查和mypy442文件通过；前端159文件1056用例通过，无未处理错误，覆盖率85.94/82.01/85.52/88.41%，格式、lint/类型和构建通过。此后Unicode预算补修和S17定位有新增改动，不能把这一轮通过视为最终树的完整验证。

最终源码提交 `eb0b596fb4d13174726d8b60b4d7c5e3fb4cb060`，backend树 `d0096a516e80d991a72c9a0b3305ccef2b525121`，后端应用树 `b974f2737e87db1b68427ef7c9f32693e0bb1b6b`，frontend树 `f5245a50446913511c1f55c0a4a21301f308ce3c`。对应完整检查日志 `remediation-mock-eb0b596-backend-full.log`、`remediation-mock-eb0b596-frontend-full.log`。该精确树最终检查通过：后端1874项、14项跳过、2项既有警告，覆盖率91.05%，Ruff格式/检查和mypy442文件通过；前端159文件1056用例、无未处理错误，覆盖率85.94/82.01/85.52/88.41%，格式、lint/类型和构建通过。检查运行期间保持本工作树的应用和测试源码冻结，后续文档收尾未改变源码树。

最终Grid浏览器补验显式设置并核对桌面viewport=1440、document=1440、页面高度2315；随后切换手机viewport=390、document=390。相同路由ID保存、优先级42、键值条件、模板数组类型及真实Mock201对照再次通过，页面异常0。记录：`remediation-mock-layout-verified-browser.log`；截图：`remediation-mock-layout-verified-desktop.png`、`remediation-mock-layout-verified-mobile.png`。之前某轮沿用了上一轮手机视口，文件名虽带desktop但实际390px，未将该截图计为桌面证据；本次通过明确尺寸断言补验。

## 项目治理合并与Mock后续交付

[PR #141](https://github.com/a3384379/FlowTest/pull/141)最终HEAD `b4f0ea592c082b6153022da47ae408e279525e2a` 的[正式Required Gate 39513064716](https://github.com/a3384379/FlowTest/actions/runs/39513064716)成功，审查线程为空且无下一页，按匹配SHA命令合并main为 `9e9d95ce6deb3a5dfd669ae6b4a7eae731055d33`。合并后[Full Regression 39517147484](https://github.com/a3384379/FlowTest/actions/runs/39517147484)已结束为成功，已核对精确head一致；该结果独立于PR门禁及正式环境验收。

数据与Mock [PR #142](https://github.com/a3384379/FlowTest/pull/142)同步该main时仅保留三份包含最新验证回执的整改文档，后端树 `d0096a516e80d991a72c9a0b3305ccef2b525121`、前端树 `f5245a50446913511c1f55c0a4a21301f308ce3c` 均与最终完整本地验证一致。当前37/73项本地完成、36项待完成、35项已合并；Mock的2项尚未合并。

## M09 远端失败定位与测试补修

PR #142 的旧HEAD `b30027ef96424b6bfdefc97d5e8555fa6b6b16cf` 对应[正式运行39517249183](https://github.com/a3384379/FlowTest/actions/runs/39517249183)最终失败：frontend-full中3个测试超时、1个错误提示唯一性断言失败，1052通过、4失败；backend/full与集成、Compose完整smoke（含S17）、Windows及升级作业通过。旧失败保留，不能将其他作业成功视为正式Required Gate通过。

测试补修提交 `0e771b434c26305cbb0bdcc2709ee527c8e07939` 将查询限制到本次render及相应表单，复用具名控件，在测试中关闭动画，等待保存后启停控件可用；服务目录fixture按实际服务ID隔离。失败保存保留输入与唯一错误提示断言，并新增真实PUT调用恰好一次的断言。未提高超时、跳过测试或弱化失败断言，没有修改产品实现。

3个具名文件30项定向测试通过，相关格式、ESLint和TypeScript通过。随后精确前端树 `eeaa1ebd93e4439fbb139ff219295e97108b2996` 的完整检查通过：159文件1056项、无未处理异常，覆盖率85.94/82.01/85.52/88.41%，格式、lint/类型和生产构建通过。后端树仍为 `d0096a516e80d991a72c9a0b3305ccef2b525121`，与最终1874项完整检查一致，未重复运行不变后端。日志 `remediation-mock-ci-scoped-targeted.log`、`remediation-mock-ci-followup-frontend-full.log`，旧失败完整日志 `remediation-mock-pr142-ci-failed.log`。

本地37项完成、35项已合并的数量不变。下一步仅以推送后最新HEAD的正式Required Gate及审查状态决定合并；不把本地通过或旧HEAD的部分远端通过当作新HEAD门禁。
