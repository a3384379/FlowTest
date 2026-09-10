# S1 修复与兼容边界

本轮实际基线为 `591641b`。不覆盖已有若依 Compose 修改；不发布、不推送。

## 下载和内容

- 修复中文项目名使四种导出共用响应头抛出 `UnicodeEncodeError` 的问题；返回 ASCII filename 和 UTF-8 filename*，跨域仅额外暴露 Content-Disposition。
- 前端优先 UTF-8 文件名，编码损坏时回退；curl/excel/bruno 备用扩展名正确。错误 Blob 解码并展示 message/code/trace_id，失败不下载。
- 导出上限为 10000，超限报错，当前版本缺失报错，不再静默遗漏。
- HAR 补齐 cookies、timings、cache、大小和 SQLite 时间戳时区等标准结构；JSON/raw/form 分开编码。无 Body 不写 postData，JSON null 保持 null。
- cURL 和 HAR/Bruno 的服务相对地址使用 `http://flowtest.invalid` 模板主机，不自动选第一环境。用户需替换为明确的环境或服务地址；本轮不执行导出的命令。
- Bruno 输出采用 version/items/http-request/header 数组/body mode 的原生结构，通过官方 `@usebruno/schema 0.29.0` 的五种 Body 类型严格校验，依据[官方集合 schema](https://github.com/usebruno/bruno/blob/main/packages/bruno-schema/src/collections/index.js)。保留旧 FlowTest 自定义 Bruno JSON 导入兼容；新结构支持当前导出的平面集合。
- Excel 的 query 列改为参数数组以保留重复键；导入兼容旧对象形式。新增 body_kind 列保留 Body 类型，公式防护继续生效。
- Multipart 文本字段按格式输出；HAR/cURL/Bruno 遇到文件引用明确返回 `EXPORT_MULTIPART_FILES_UNSUPPORTED`，不生成伪成功文件。Excel 保留引用，迁移到其他项目需重新绑定，未自动读取附件。
- 集成回归发现重复 Query 导致接口创建 500：仅合并契约描述中的同名参数声明，原始请求仍保留全部重复值。

## 环境

- 接口控制台与工作流共享用户/项目隔离的选择，浏览器 origin 自然隔离实例；模块卸载、刷新及其他窗口的 storage 事件均读取同一选择。
- 多环境首次进入保持未选择；唯一环境可初选并保存。失效的显式选择保留失效状态、显示提示并阻止执行，不能回退剩余第一项。
- 存储不可用/配额异常不显示成功选择；提供错误提示。
- 保留现有 RequestTargetResolver 及网关前缀拼接。显式 Service 丢失时报错；绝对 URL 或协议相对 URL 在执行解析时返回 `API_PATH_NOT_RELATIVE`，提示迁移到环境/Endpoint 配置。
- 本次运行使用服务器接收到的 environment_id 和既有执行快照，之后切换页面选择不改变已提交目标。

## 与后续阶段的边界

S2 已补齐默认 OFF、项目策略 API/UI、入口短路、迁移、任务策略快照和规范同步；S3 已补齐环境/工作流归档、引用保护和服务端接口选择；S4 已补齐资源身份隔离的本地草稿恢复；S5/S6 已补齐 Quick MCP、工具发现、Skill、示例和评测同步。具体状态见 [`FLOWTEST_UX_QUICK_MCP_CHECKPOINTS.md`](FLOWTEST_UX_QUICK_MCP_CHECKPOINTS.md)。

本笔记只记录 S1 的实现和兼容边界。独立 Compose 验收使用当前源码、Standalone SQLite 和两个真实 HTTP Mock；它不等于 Celery/Runner 独立部署验收，也不等于 Windows 实机验收。完整多页签交互、20 次性能采样、超过 100 条接口的完整下载矩阵、升级/回滚和 Windows 包仍需按 S7 在相应环境验证。
