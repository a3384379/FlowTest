# M26 平台管理整改回执

对应冻结审计：F-PLAT-01、F-PLAT-02。开发基线：M25 独立提交 `761b87b27b9be9afe83614de90b7e273e51ed108`；本模块独立提交。

## 实现

- 选择身份明确区分能力版本、插件、Runner Pool，写入 URL。切换库存模式清空旧选择；目录搜索、翻页与所选对象分离，页外对象通过精确只读接口恢复。未选择时提示选择对象，不隐式替换为首项。
- 插件详情展示返回的版本、完整 Digest、仓库、签名声明身份、状态和时间；Runner 展示池、成员、标签、能力、负载、状态和心跳。执行面开启且当前有管理权限时才提供所选 Pool 的只读入口。
- 能力检查器包含摘要、输入 Schema、输出 Schema、配置 Schema、策略与来源页签。复用现有只读阅读器，提供完整内容复制、搜索、格式化、换行和下载。顶层字段表最多预览 200 项；原文沿用 300 行或 64,000 字符的预览上限，完整复制和搜索不截断。
- 完整哈希与 Digest 可复制。默认/最大超时、网络协议、DNS、Snapshot 配置/哈希/Digest/凭据材料策略和原始策略声明来自实际返回值；缺值显示未提供，未知策略按原值降级。没有固定成功安全宣言，也没有把能力声明当作安装或项目的实际采集策略。
- 搜索在服务层覆盖对应完整库存后按现有 Page 合同分页。能力复用现有精确版本 GET；插件和 Pool 原接口只有目录，因此补充同角色边界的精确只读 GET。没有开放安装、令牌、凭据或执行写入。
- 平台 Pool 目录、total、精确详情收紧到执行面已有的当前组织及共享 Pool 范围；无组织系统管理员保留全局合同。只调整读取边界，不改变相关写入。
- 只显示当前模式的读取错误；刷新失败的缓存目录/详情明确标记为上次读取。查询缓存包含对象类型、版本、用户、组织和管理员状态，避免切换、迟到结果或权限撤销串详情。关闭态明确为已有库存只读检查。

## 涉及文件

- 后端：`app/api/v1/endpoints/capabilities.py`、`app/services/capabilities.py`、`app/repositories/capabilities.py`、`tests/test_capability_sdk.py`。
- 前端：`PlatformCapabilitiesPage.tsx`、页面测试、`features/capabilities/capability-service.ts`、新增 `features/capabilities/PlatformInspector.tsx`。
- 未修改冻结审计、共享进度、依赖、CI 治理、数据库模型或迁移。

## 针对性验证

- `make test-frontend-targeted TARGETS='["src/pages/PlatformCapabilitiesPage.test.tsx", "src/features/api-console/ResponseCodeReader.test.tsx"]'`：2 文件、21 项通过。
- 页面反例包括能力切到空插件不残留、插件/Pool URL 页外恢复、库存第 101 项可达且保留选择、完整三份 Schema 复制与搜索、缺字段、未知及原型名称策略值、切模式后的旧错误清理、版本及组织迟到结果隔离、同用户管理员权限撤销和普通角色无管理读取。
- 阅读器现有用例验证超出预览范围的搜索与完整复制、复制失败提示，以及格式化不改变原值。
- `make test-backend-targeted TARGETS='["tests/test_capability_sdk.py", "tests/test_workflow_contract.py"]'`：2 文件、16 项通过。覆盖 101 条库存、目录搜索及分页、精确读取、管理员/普通角色边界、未知对象和标准 trace ID、组织及共享 Pool 的列表/total/精确读取，无组织管理员全局合同保持。
- 受影响 Ruff 格式及规则、ESLint、Prettier、TypeScript 检查和 `mypy app` 通过。
- 原始日志保留在本工作树 `output/validation/m26-platform/`（未提交生成物）。首轮页面测试失败为旧正则同时匹配错误通知与表格空态，改为精确公开文案断言后通过；未调整测试超时、重试或覆盖率门槛。
- 独立只读子审指出的 Pool 组织范围、旧模式错误残留、未知策略原型属性三项问题均已修复，并增加公开行为或 API/服务反例。

## 条件环境与验收边界

尚未执行真实 GUI、完整 `make check`、前端正式构建、Compose 端到端、真实插件签名/安装或外部 Runner 接入；正式最新提交门禁、合并后 CI、发布验收由整合负责人分别记录。局部通过不代表这些验收通过。

真实 GUI 可使用原有兼容预览库存，无需启动任何任务：管理员进入 `/platform`，选择一条实际能力，再切换空插件模式核对检查器清空；重新选择能力，依次核对三份 Schema 及策略页、搜索/复制；通过返回的真实插件/Pool ID 恢复 URL，刷新及目录切页核对选择身份；切其他组织或普通角色核对库存边界与详情消失。插件安装按钮始终禁用。空插件/空 Pool 使用真实空态，不用示例记录替代；101 条库存和迟到响应已由隔离测试夹具验证，未向共享 QA 数据库写入合成库存。
