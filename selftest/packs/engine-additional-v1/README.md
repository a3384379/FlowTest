# 附加原生引擎包

固定 11 个场景，内部类型 `pack_id=extended-v1`、`pack_version=1.1.0`。这一版完整黄金值摘要为 `b8280f525c23300fba7bbe0227b6debbac5af2375399ba323bd34e97ab4f7a0a`；原 19 项扩展包的摘要保持 `8200b66735e0d8b23cc21016fc57612181981a7c9f8e73a5cdc2fd70f7578df4`。

场景包含轮询时限、请求预算耗尽、Finally 失败、Parallel 并发上限、嵌套 Break/Continue、非法位置 Return、Switch 命中、工作流全局时限、固定版本子流 Return/Finally、数据行 `0` 与 `false`。工作流全局时限保留真实 `cancelled`，Finally 失败保留真实 `failed`；O 按运行前黄金值核对节点、阶段、尝试数与错误码，不改原始执行结论。

`dependencies.json` 单独固定子流两版完整定义与 Dataset 行。`acceptance-requirements.json` 同时固定包摘要和依赖摘要。`prepare_engine_additional_pack` 通过公开 API 安装并在 Run 前冻结真实 API、子流 v1、文件 SHA、子执行黄金值，再用既有 Case → Suite → Plan 路径执行；发布子流 v2 后仍要求父流程引用 v1。

CI 只读接口只投影节点状态、断言摘要、子执行引用、Dataset ID/SHA/行数和子流/API 固定版本。M 管理面只增加请求 UUID 的 begin/end/active、结果类型与共享预算计数，不收集新的业务 body/header。O 独立计算峰值并精确核对子执行集合。

M 预算按 `parent_batch_key + nonce` 冻结，显式绝对截止时间不延长，SQLite 原子限制最多 500 次处理，跨场景、cleanup 和 Native API phase 共享；删除 namespace 不重置。第 501 个请求可以到达 M，但返回标准 429 与 trace ID，不生成处理回执；`rejected_count > 0` 阻断验证。这一限制覆盖 M 的处理副作用，B 目标的独立代理硬限制仍未实现，不能把两者等同。

超时用例可能在 A 终态之后由 M 完成。O 只在剩余批次期限内、至多 5.5 秒读取真实同 UUID 的结束事实；截止时仍 active 就保留未完成证据并返回 incomplete，不制造结束时间。

Dataset 没有公开 DELETE file 接口，因此完整通过必须等待 owned A 整栈清理。`finalize_engine_additional_cleanup` 只接受预先绑定的 project/container/volume/image/nonce，并独立确认精确资源都已不存在；清理之前的 O 结果必须为 `OWNED_ASSET_DISPOSAL_PENDING`。原始执行状态不随最终清理而改写。

本包已接入当前 H/O 与 CI 入口。Full、Compact 的 final8 构建已实际执行 11 场景，并在所属栈销毁后完成独立核验；安全报告分别保存在 `output/selftest-validation-20261023-s4/public/full-final8`、`compact-final8`。这些是对应构建的历史证据，不能证明后续源码或全部 94 项验收通过。产品后台模板仍以部署允许的模板集合为准，不能从 CLI 包已运行推断所有场景都可在页面选择。
