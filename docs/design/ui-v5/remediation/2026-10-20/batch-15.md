# M13 环境实验室整改记录

依据：[完整审计 M13](../../audits/2026-10-19/complete-audit.md#m13)、[详细方案 M13](../../audits/2026-10-19/remediation-plan.md#m13)，对应 `F-ENV-01/02`。

**两项已实现并通过本地完整检查、真实API及浏览器专项，计入46/73项本地完成；27项待完成，39项已合并。** 本地约63%、合并约53%分开统计，最新HEAD的GitHub交付尚需确认。

## 完整模板维护

注册和创建新版本共用可视化表单，默认单web快捷配置保留；每个版本可维护1至5个服务、每服务0至32个环境变量及0至4个依赖、0至10个HTTP GET Seed。镜像Digest、端口、HTTP/TCP健康检查及其状态码/间隔/超时/次数、CPU/内存/PID/UID/GID和TTL均有明确字段；支持服务排序。只读根文件系统、Drop ALL和No New Privileges固定开启，未增加Compose、命令、脚本或卷字段。

新版本使用所选旧版本的全部manifest，不取第一个服务/Seed重建。字段差异针对该固定旧版本展示，描述与标识保留原模板语义。高级JSON导出当前表单；修改后必须经过同一合同校验并显式应用，未应用时禁止提交。未知字段、缺Digest、循环/缺失依赖、重复名称、TTL关系和边界均给出错误；服务端继续独立校验与签名。关闭、离开页面和卸载边界保护未保存输入，提交中禁止修改或关闭。

- 实现：[共用编辑器](../../../../../frontend/src/features/environments/EnvironmentTemplateDialog.tsx)、[结构化字段](../../../../../frontend/src/features/environments/EnvironmentManifestFields.tsx)、[声明式合同校验](../../../../../frontend/src/features/environments/environment-template-manifest.ts)。
- 行为回归：[编辑器测试](../../../../../frontend/src/features/environments/EnvironmentTemplateDialog.test.tsx)、[页面测试](../../../../../frontend/src/pages/EnvironmentLabPage.test.tsx)。

## 固定版本与完整目录

模板目录改为数据库分页、稳定排序和字面搜索；总数与本页来自同一SQL快照，空页仍有正确总数。Provision选择器使用自己的可用版本目录，不受主目录页影响，支持分页、名称/标识/说明查找和准确UUID读取。选定版本独立读取，按该版本设置默认与最大TTL；读取失败保留目标和trace，可精确重试，停用对象不能Provision。

新增全局准确版本GET，保留原全局目录可见性：活跃模板对已认证用户可读，停用模板仅管理员全局可读。另增项目实例绑定版本GET，复用现有实例READ及项目归属检查，允许实例读者核查该实例自己的原始停用配置；不扩大其他停用模板的全局可见性。

读取核查原template_version_id、key、版本号、manifest哈希和签名。无权限/跨项目/缺失返回标准404与trace；损坏或签名不符返回标准409与trace。不替换为最新版本，不迁移实例快照，不产生Provision、清理、审计写入或其他命令。客户端也核查项目、实例ID及固定绑定信息。

- 实现：[适配路由](../../../../../backend/app/api/v1/endpoints/environment_lab.py)、[服务与签名校验](../../../../../backend/app/services/environment_lab.py)、[原子目录分页](../../../../../backend/app/repositories/environment_lab.py)、[选择器](../../../../../frontend/src/features/environments/EnvironmentProvisionCard.tsx)、[SDK](../../../../../frontend/src/features/environments/environment-service.ts)、[工作区状态](../../../../../frontend/src/features/environments/use-environment-lab.ts)。
- 回归：[真实API与授权/签名测试](../../../../../backend/tests/test_environment_template_reads.py)、[SDK身份校验](../../../../../frontend/src/features/environments/environment-service.test.ts)、[迟到响应与卸载](../../../../../frontend/src/features/environments/use-environment-lab.test.tsx)。

## 额外复审与修复

1. 停用原先只刷新目录，所选版本和实例绑定详情仍缓存“可用”。新增公开页面测试复现1失败/9通过，补全三类查询失效后，当前选择器与实例详情立即显示停用状态；原manifest不变。真实浏览器以一次204停用验证两处同步。
2. 健康检查输入使用一位小数精度，会把合同允许的0.15秒改为0.2秒。新增公开表单测试复现1失败/3通过，改为保留合法浮点精度，整数限额仍为整数；真实页面填入、失焦及字段校验后仍为0.15秒。
3. 手机资源详情四列表格虽然不溢出页面，但哈希、Runtime和安全说明挤压严重。改为手机单列键值，镜像逐个标注服务；390px确认每行两格，桌面恢复四格。标题/排序按钮分行，变量/Seed删除操作独立成行。
4. 继续滚动至编辑器底部发现，栅格负边距及安全Tag使内部宽361px超过326px。先用仅浏览器预览定位，再将表单留白和Tag换行落入源码；重新加载编译产物确认body宽/scrollWidth均326px，服务标题完整，底部Seed及操作可见。没有通过隐藏横向溢出裁掉内容。

新旧对象切换及卸载后，迟到的成功/失败不会关闭当前编辑器、导航或弹出过时反馈。写入需权限成功读取，Viewer保持只读；自动脱敏/采集策略未改，也没有扩充日志或采集数据。

## 检查与精确源码

- 修改前前端EnvironmentLabPage的7项和后端test_environment_lab的7项通过。
- 后端具名read/lab两文件11项通过，覆盖22版本跨页/空页/字面%_搜索、active_only、管理员/普通用户/Viewer、自己原始停用绑定、跨项目/缺失、损坏及签名篡改，无额外运行/审计副作用。完整backend树 `b10fd948e99922afa1dacaf6ced5914e8fd17622` 的Ruff格式/检查、mypy442文件及1886项测试通过，14项既有跳过、2项既有警告，覆盖率91.08%。日志 `remediation-environment-backend-full.log`。
- 最终前端4个具名文件21项通过，另手机详情变更后页面10项复验通过。包含多服务/依赖/多个Seed保留、JSON拒绝/应用、差异、精确版本查询/失败重试、停用同步、0.15精度、只读及迟到反馈保护。
- 最终源码 `8101b8aa17dcf6a962d27fecf2a0ff3d6a2829b4` 的frontend树 `feb944c5676ae60a611d28940d4b8fd85f4eb2f2`：格式、ESLint/TypeScript、169文件1117项测试、构建通过，无未处理异常；覆盖率85.97/81.98/85.74/88.54%。日志 `remediation-environment-spacing-final-frontend-full.log`。检查期间应用和测试源码冻结，后续只有文档收尾。
- 中间版本分别1115、1116及1117项完整通过，只归属于相应树；最后手机样式改动独立重验，不将更早结果套用为最终源码。开发期间一次新增测试使用了不支持的ByRole exact参数，被类型检查拦截后修正，未跳过检查。

## 隔离 PostgreSQL 与浏览器证据

使用自有Compose `flowtest-product-completion`、端口13078和隔离Chromium；用户3000端口及其他项目未改。项目 `3d50a9e8-95a6-4218-851d-1bdca166f17b`，明确标记 `隔离合成审计M13-1792561163760`。

1. GUI注册两个服务web/api，api依赖web、端口8081、CPU300，两项Seed分别web/与api/seed-two。首次创建合成503保留输入和trace，重试仅一次真实201。模板 `c10d8ada-684a-4a68-b3af-9daf68112d35`，原v1 `2977daff-7800-45e7-85d7-a43c93e3c2f6`。
2. GUI从v1创建v2，完整保留服务、变量、依赖、健康和Seed，修改api CPU400与最大TTL12000；查看差异、拒绝未知command、应用合法JSON及取消关闭均验证。真实v2为 `bab36ecb-90c6-4956-b10a-0a7fcd0c0e66`；重新读取v1仍CPU300/最大TTL14400，哈希 `54e158fc0d336d072e6a876a093b56ce0c537293f00d48f3ced9b4c12ffb7933` 不变。
3. 再创建20个明确的合成模板版本，目录22个版本，第1页20条不含v1；选择器独立第2页/准确UUID可读原v1。仅用于分页，没有启动这些版本。
4. 实例 `351c75b2-34c1-49ac-b913-763fd200af10` 是明确标注的**数据库合成历史fixture**：failed/cleanup completed，错误说明写明“仅用于版本读取验收，未启动容器”，保留原v1签名快照。它用于检查历史读取，不能作为真实Provision/Seed/清理的成功证据。本轮没有启动环境Docker daemon或环境Runner；原运行路径由既有后端专项和后续正式Compose/S26门禁覆盖。
5. 对该绑定读取合成503，客户端两次尝试后显示trace且不展示其他配置；显式重试真实200恢复同一v1。以另一个有权访问的合成项目读取相同实例得到真实404/trace、无其他配置回退；返回原项目恢复同一绑定。
6. 真实停用一次204后，实例绑定及当前选择器立即显示停用；原CPU/TTL/哈希不变，Provision禁止。读取/截图/负向表单检查均没有创建新版本或运行。全流程没有页面未处理异常。
7. 最终手机390/document390，详情改为单列键值；模板弹窗稳定几何x8/y24/宽374/高804，标题与按钮不挤压，内部body326/scrollWidth326。桌面1440恢复两列描述。动画中的缩放几何未作为最终验收，已等transform none/动画结束重新测量和截图，并逐张目视核对。

主要日志位于忽略的output/playwright/audit-20261019：`remediation-environment-editor-browser-resume-r2.log`、`remediation-environment-offpage-seed.log`、`remediation-environment-bound-browser.log`、`remediation-environment-final-review-resume.log`、`remediation-environment-scope-browser-r2.log`、`remediation-environment-mobile-final.log`、`remediation-environment-register-stable.log`、`remediation-environment-mobile-controls-final.log`。最终资源详情、服务表单及Seed手机截图均已目视检查。

自动化自身的失败记录保留：下拉菜单虚拟选项重复，改为可见真实选项并从未保存表单恢复；嵌套has定位错误，DOM检查确认对应字段错误实际存在后修正定位；跨项目错误因自动重试产生新trace，改为验证最终错误trace而非强行匹配第一次响应。未增加超时/重试或削弱业务断言，没有重复已完成的模板写入。

## 交付边界

本批没有新增数据库模型/迁移、任意运行能力、日志或采集。最新HEAD的正式Required Gate、审查、合并和合并后Full Regression仍需单独确认，未声称正式部署或实体Windows验收完成。全站73项仍未全部完成，M14性能实验室及后续R3/R4继续整改。
