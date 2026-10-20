# 第九批：多协议工作台整改

对应原审计 M05 的 F-PROTO-02、03、04，并补充 F-PROTO-01 的事件协议及会话边界回归。原始审计与方案保持不变；本文件记录实施与验证，不代替全站设计签收。

**当前状态：F-PROTO-02、03、04均已实现并完成本地验收，计入33项本地完成。** GitHub最新提交门禁、合并和合并后回归另行确认，不等同于已合并或全站设计签收。

## 目录、链接与固定版本

- URL分别保存GraphQL Schema、gRPC Descriptor、Kafka来源、WebSocket来源及目录页码；Kafka消息Schema使用独立ID与页码。各模式的参数保留，前进/后退同步。
- 已选资产独立于当前目录页。页外ID使用授权只读接口补取，目录翻页不能隐式改选首项；首次未指定ID时才规范化默认选择。
- 缺失、非法、无权限或跨项目对象明确显示标准错误及返回的Trace ID。非法模式、ID和页码停止当前编辑/调试范围，不静默回退。
- Kafka消息Schema按现有模型仍是项目内资产，不伪造与单一事件源的归属关系。读取时同时校验当前来源是本项目Kafka来源，以及Schema属于本项目Kafka协议。
- 当前协议工作台内部的模式、资产和页码切换保留请求内存草稿；离开模块/项目仍通过现有统一草稿保护提醒。修复了模式切换后自动补全版本链接再次弹出确认的问题。

## 真实请求配置与回包归属

- GraphQL提供Authorization、可启停Header、Operation Name及超时；gRPC提供独立Authorization、可启停Metadata及超时，保留TLS/mTLS与Credential引用。
- 重复键按大小写归一识别；专用Authorization和高级项不能重复配置；禁用项不发送。保留现有后端校验、权限与安装策略，不读取Credential材料。
- 请求草稿按项目、协议、资产ID、版本和内容哈希保存于当前内存；认证输入不写入localStorage/sessionStorage。退出或身份失效时清除协议草稿及相应脏标记，同账号重新登录不能恢复上次认证输入。
- gRPC凭据列表刷新后，失效引用明确标记为不可用，并禁用mTLS提交。凭据或权限读取失败时不沿用旧查询数据授权新提交；保留已填请求，提供错误和重试。缺失或不支持的方法不会被猜成Unary；合法结构样例可补充旧版本缺失的方法摘要。
- Kafka Produce/Consume与WebSocket Exchange冻结提交时的请求，并绑定来源版本和请求序号。切来源、编辑请求、卸载或发起较新操作后，旧响应/错误不能覆盖当前证据；较早的Produce不能覆盖较新的Consume。
- GraphQL/gRPC在卸载提交阶段关闭结果接收范围；错误证据可查看标准错误及Trace ID。不会以重试按钮自动重发有副作用的调试。
- 三种导入窗口在保存中冻结表单；权限撤销后禁止提交。允许关闭窗口，已发出的保存继续在原范围完成；迟到回包不得关闭或重置新打开的窗口。

## 契约结构与输入引导

- 从数据库中已有的规范化契约解析结构，不依赖截图或硬编码的Query/Mutation名称。结构读取不执行网络Introspection、Reflection、DNS、Credential解密或协议调试。
- GraphQL展示真实操作根、对象/输入对象/接口/联合/枚举/标量、字段与参数类型。必填性考虑NonNull及默认值，不能把有默认值的参数误标为必填。
- gRPC展示服务、方法、调用类型、请求/响应消息、枚举、嵌套类型、JSON字段名、Repeated、Map和Oneof。Client/Bidi Streaming只读并说明不能调试。
- 结构树按需展开、每页25项、同层最多展开一个分支。循环引用停止自动展开；超过层级上限仍可选择节点进入详情。支持返回上层、结构首页与只读源文档。
- GraphQL按真实根字段生成操作及必填变量；对象返回值使用合法的`__typename`选择。gRPC按Descriptor生成Protobuf JSON输入。只有显式点击才填入草稿，不修改Schema版本，不执行请求。
- 自定义标量、递归/深嵌套、样例字段超限或需专门Protobuf JSON格式的类型明确说明无法生成完整样例，不用不完整对象宣称合法。
- GraphQL错误路径按当前冻结操作解析别名与Fragment，定位真实根字段。定位专用解析限制Token和根节点遍历次数，去重Fragment展开，不调用执行校验或展开完整操作。定位后，再沿返回类型查看子字段。多操作或路径不能唯一定位时返回明确错误；不会猜测别名等于字段名。gRPC可定位当前方法契约。
- 源文档预览上限64 KiB，超出时明确标记前缀；Descriptor二进制用Base64表示。UTF-8前缀采用增量解码，中文被截断时不会将整个文档误当二进制。内容哈希可完整复制。
- 桌面采用目录、编辑器、检查器三列；中等宽度两列、窄屏一列。修复实测390px下仍按桌面最小宽度撑至745px的问题。

## 接口与分层

| 能力                  | 接口/实现边界                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------- |
| 精确读取GraphQL/gRPC  | `GET /graphql/schemas/{id}`、`GET /grpc/descriptors/{id}`，复用ProtocolAssetService授权读取 |
| 精确读取事件源        | `GET /event-sources/{id}`，校验项目及协议kind                                               |
| 精确读取Kafka消息契约 | `GET /event-sources/{sourceId}/schemas/{id}`，同时验证来源和项目内Kafka契约                 |
| 分页结构/只读源文档   | `GET /protocol-assets/{id}/structure`，返回固定身份、节点页、可选样例、诊断和文档格式       |
| GraphQL错误字段定位   | `POST /graphql/schemas/{id}/locate-error`，只读解析，不执行操作                             |
| 纯领域解析            | `graphql_structure.py`、`grpc_structure.py`及闭合dataclass合同，不引用HTTP框架/ORM/基础设施 |
| 路由与服务            | 路由仅适配请求/响应；服务先授权，后调用纯领域解析，使用标准错误封装                         |

本批不改变数据库模型，无新增迁移；保留既有API兼容、不可变资产版本及真实调试处理链。未改变诊断捕获/脱敏默认值，未增加日志采集。

## 验证记录

1. 首次完整`make check`：后端1837通过、14跳过、2项既有警告、90.99%；前端153文件1014通过，无未处理异常，覆盖率85.78% / 82.04% / 85.24% / 88.25%，包含格式、Ruff、mypy、lint、类型与生产构建。日志`remediation-protocol-workbench-make-check-r1.log`。后端树`0ffb5179da57dd96e770f06f607e85af9f97d552`，前端树`7f8dc8c1347f74ed9f3ad33e48c2bc1248bd9cd1`。
2. 此后复审新增：协议查询切换保护、同账号退出清理、可展开结构树和UTF-8边界，不能用首次完整检查替代最终检查。导航/会话跨模块72项通过；结构与UTF-8后端15项通过；树及工作台40项通过。第二轮完整检查通过：后端1837项、91.00%，前端154文件1018项，日志`remediation-protocol-workbench-make-check-r2.log`。该轮之后继续修复只读定位预算/名称歧义/损坏Schema，以及权限和凭据读取失败时沿用旧值的问题；最终源码验证如下。
3. 最终浏览器GraphQL/gRPC通过：第2页固定版本重载、真实契约样例填入、协议间认证隔离、返回后草稿恢复；桌面1440px与手机390px的文档宽度均等于视口，无页面错误，未执行调试。日志`remediation-protocol-final-schema-browser.log`。
4. Kafka/WebSocket实际保存消息Schema选择和来源参数、返回后请求草稿恢复、离开模块仍保护草稿、重载后固定Schema不变、无效模式明确报错；没有执行Produce/Consume/Exchange。事件工具栏窄屏溢出修正后，四种协议均完成1440px/390px截图；最终事件范围日志`remediation-protocol-final-event-scope-browser.log`。事件脚本曾因REST入口的嵌套按钮角色定位失败中断，修正测试定位后继续验证，未将工具超时当产品失败或成功。
5. 浏览器使用自有Compose与隔离Chromium，`http://127.0.0.1:13078`。真实创建21个合成GraphQL资产形成第2页，以及专用Kafka/WebSocket来源与消息契约；只使用该审计项目，不发送协议请求。早期移动截图用于记录缺陷，不作最终验收。
6. 最终后端：1841通过、14跳过、2项既有警告、覆盖率90.98%，格式/Ruff/mypy通过（440文件）。日志`remediation-protocol-final-backend-full.log`；后端树`ef5b46dba111d6f7da3ecf387050d987d0112a74`。
7. 最终前端：154文件1020项通过，无未处理异常，语句/分支/函数/行覆盖率85.82% / 82.08% / 85.27% / 88.28%；完整格式、lint、TypeScript与生产构建通过。日志`remediation-protocol-final-frontend-full.log`；前端树`e31166020f136eb43d58d25b13a547e350dac280`。最终源码提交`a2968297293c14944d04357f63a9a3ee6f75a2dd`；后端完整运行时的前端补修不改变已验证后端树，两侧精确源码独立记录。
8. API专项60项及真实Compose只读定位验证通过：23层重复Fragment引用有界去重定位到真实根字段，歧义操作返回422和Trace ID；没有执行请求。日志`remediation-protocol-ambiguous-invalid-after.log`、`remediation-protocol-readonly-location-browser.log`。凭据/权限失败后的具名UI补修42项通过，并纳入上述最终1020项完整前端运行。
9. 分支已推送GitHub，并在前置PR #139合并为`722d72f`后同步main。仅解决重复合并产生的上下文冲突，合并后后端/前端树逐一确认与上述最终已验证树相同。接下来独立确认本批PR最新提交的正式Required Gate与审查线程；PR #139的门禁只属于请求目标批次，不代表本批已合并。

## 验收边界

- 未执行外部GraphQL/gRPC/Kafka/WebSocket真实目标的连通性或调试验收；本批验证管理、结构、请求提交合同与归属，真实协议运行继续使用原处理链和既有集成覆盖。
- 生成的是契约结构样例，业务取值仍由使用者填写；无法可靠生成时明确停止。
- 源文档64 KiB是预览边界，不把截断内容宣称为完整导出。
- GitHub最新提交正式门禁、合并后回归与正式部署单独记录。
