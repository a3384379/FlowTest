# ADR 0045：内置 Java/Spring Provider 的静态分析边界

## 状态

已接受，V6.1 S57 起执行。

## 背景

S52 已有有界 Java/Spring 静态分析 POC，可以识别 Spring MVC、DTO、Bean Validation、Service/Feign、
MyBatis/JPA、Enum、Exception 与 Kafka 结构，但它只在领域测试中直接调用。产品入口仍要求调用方先自行生成
`JavaEvidenceSubmission`，因此 FlowTest 尚不能作为内置 Provider 接收源码快照、生成证据并推进 Context
Revision。

直接让 FlowTest 克隆任意仓库、执行构建工具或加载目标 Classpath 会扩大 SSRF、Credential、供应链和任意代码
执行边界，也会使同一 Context Revision 无法证明输入版本。因此 S57 必须先建立不执行目标代码的正式入口。

## 决策

- 新增 `flowtest.ingest_java_source_snapshot` MCP Tool 与对应 HTTP API。调用方提交显式
  `source_ref`、不可空 `source_revision`、项目范围 `subject_ref` 和仓库相对 `.java` 文件。
- 输入最多 50 个文件、总计 1 MiB、单文件最多 256 KiB；拒绝绝对路径、`..`、重复路径、非 Java 文件和
  `execute_analyzed_code=true`。
- Provider 身份由服务端固定为 `flowtest-java-spring@1.0.0`，请求不能覆盖或伪造；MCP Server 契约升级为
  `s57-java-spring-provider-v1`。
- 复用 S52 的纯领域静态分析器，不克隆仓库、不解析本机路径、不启动编译器、构建工具、JVM 或目标代码，
  也不发起网络请求。
- 源码只存在于请求内存中。持久化内容仅包含规范化结构 Claim、来源 Revision、指纹、可靠性与安全 Warning；
  原始源码不进入 Context Evidence、Audit、日志或响应。
- 分析结果通过已有 `TestContextService.ingest_adapted()` 完成项目授权、Revision 锁、重复证据、容量、冲突、
  映射与审计处理，不建立第二套 Evidence 生命周期。
- 如果源码没有产生任何受支持 Claim，返回带 Trace ID 的稳定
  `JAVA_SOURCE_EVIDENCE_NOT_FOUND` 422；派生 Claim 未通过敏感信息或结构校验时返回
  `JAVA_SOURCE_EVIDENCE_INVALID` 422，不把验证内容或原始源码写入错误日志。
- API 返回安全的结构化分析结果以及新 Context Revision 和 Entity Mapping，使调用方能够看到静态分析
  Warning。State Knowledge 派生与用户侧 Context Inspector 在 S57 后续独立 PR 完成。

## 结果

FlowTest 获得第一个正式内置 Java/Spring Provider 入口，同时保留 External Code MCP 的开放模式。相同版本
源码和 Provider 产生确定性 Claim；无法静态确认的继承、Lombok、Jackson、JPA 或动态注解语义继续
Fail Closed 并要求人工复核。

调用方仍负责读取它有权访问的仓库并提交版本固定的源码快照。服务器不会代替调用方持有 Git Credential，
也不会把请求中的仓库引用解释为可访问 URL。

## 否决方案

- 由 API 接收任意 Git URL、Credential 并在服务端克隆。
- 在 API/Worker 进程中运行 Maven、Gradle、Javac 或加载目标 Classpath。
- 允许调用方声明内置 Provider 名称和版本。
- 把原始源码保存到 Evidence、Audit 或日志以便后续重新分析。
- 为内置 Provider 新建平行 Context、Mapping 或 Proposal 生命周期。
