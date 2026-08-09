# ADR 0002：变量与 Header 作用域

状态：Accepted

变量覆盖顺序为 Global → Project → Environment → Workflow → Dataset → Runtime。Header 覆盖顺序为 System → Project → Environment → Workflow → API → Runtime。后级覆盖前级，解析结果始终保留最终来源。
