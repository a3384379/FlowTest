# ADR 0003：Workflow 持久化契约

状态：Accepted

Workflow 使用版本化 JSON 契约保存 Node、Edge、Settings 和结构化 Field Mapping。草稿可修改，发布版本不可变。发布前必须验证唯一节点、唯一 Start、至少一个 End、引用完整且无环。
