export const nodeLibraryCategories = [
  '基础',
  '接口/协议',
  '控制与校验',
  '数据与存储',
  '流程复用',
] as const

export type NodeLibraryCategory = (typeof nodeLibraryCategories)[number]
export type NodeRegistryKey =
  | 'api'
  | 'graphql'
  | 'grpc'
  | 'kafka.produce'
  | 'kafka.consume'
  | 'websocket.exchange'
  | 'extract'
  | 'assert'
  | 'condition'
  | 'delay'
  | 'dataset'
  | 'sql'
  | 'redis'
  | 'subflow'
  | 'for_each'
  | 'control.foreach'
  | 'control.repeat'
  | 'control.if'
  | 'control.switch'
  | 'control.while'
  | 'control.do_while'
  | 'control.until'
  | 'control.parallel'
  | 'control.try'
  | 'control.group'
  | 'control.fail'
  | 'control.return'
  | 'end'

export type NodeIconKey = 'api' | 'control' | 'data' | 'flow' | 'timer' | 'end'

export type NodeRegistryItem = {
  id: NodeRegistryKey
  category: NodeLibraryCategory
  icon: NodeIconKey
  label: string
  description: string
  keywords: string
  prerequisite?: string
}

export const nodeRegistry: readonly NodeRegistryItem[] = [
  {
    id: 'delay',
    category: '基础',
    icon: 'timer',
    label: '等待',
    description: '在继续执行前等待指定时间',
    keywords: '等待 延时 delay timer',
  },
  {
    id: 'end',
    category: '基础',
    icon: 'end',
    label: '结束',
    description: '标记一条主流程路径完成',
    keywords: '结束 完成 end',
  },
  {
    id: 'api',
    category: '接口/协议',
    icon: 'api',
    label: '接口请求',
    description: '调用已发布的固定版本 HTTP 接口',
    keywords: 'HTTP REST API 接口 请求',
    prerequisite: '需要已发布接口',
  },
  {
    id: 'graphql',
    category: '接口/协议',
    icon: 'api',
    label: 'GraphQL 请求',
    description: '基于 Schema 执行 GraphQL 查询或变更',
    keywords: 'GraphQL Schema query mutation 协议',
    prerequisite: '需要 GraphQL Schema',
  },
  {
    id: 'grpc',
    category: '接口/协议',
    icon: 'api',
    label: 'gRPC 调用',
    description: '基于 Descriptor 调用 gRPC 方法',
    keywords: 'gRPC protobuf descriptor unary streaming 协议',
    prerequisite: '需要 gRPC Descriptor',
  },
  {
    id: 'kafka.produce',
    category: '接口/协议',
    icon: 'data',
    label: 'Kafka Produce',
    description: '向配置好的 Kafka Topic 写入消息',
    keywords: 'Kafka Produce Topic 消息 事件',
    prerequisite: '需要 Kafka 事件源',
  },
  {
    id: 'kafka.consume',
    category: '接口/协议',
    icon: 'data',
    label: 'Kafka Consume',
    description: '从配置好的 Kafka Topic 消费消息',
    keywords: 'Kafka Consume Topic 消费 事件',
    prerequisite: '需要 Kafka 事件源',
  },
  {
    id: 'websocket.exchange',
    category: '接口/协议',
    icon: 'api',
    label: 'WebSocket Exchange',
    description: '通过已配置事件源交换 WebSocket 消息',
    keywords: 'WebSocket WS 消息 事件 exchange',
    prerequisite: '需要 WebSocket 事件源',
  },
  {
    id: 'extract',
    category: '控制与校验',
    icon: 'control',
    label: '提取变量',
    description: '从上游结果提取数据并写入流程变量',
    keywords: '提取 变量 extract JMESPath',
  },
  {
    id: 'assert',
    category: '控制与校验',
    icon: 'control',
    label: '断言校验',
    description: '校验上游结果是否满足预期',
    keywords: '断言 校验 assert expect',
  },
  {
    id: 'condition',
    category: '控制与校验',
    icon: 'control',
    label: '条件判断',
    description: '根据比较结果进入是或否分支',
    keywords: '条件 分支 condition true false',
  },
  {
    id: 'control.if',
    category: '控制与校验',
    icon: 'control',
    label: '条件判断 · 控制块',
    description: '在内联是/否区域中运行选中的路径',
    keywords: 'IF 条件 分支 控制块',
  },
  {
    id: 'control.switch',
    category: '控制与校验',
    icon: 'control',
    label: '多分支判断',
    description: '按值匹配首个分支，并执行默认区域',
    keywords: 'Switch case 多分支',
  },
  {
    id: 'control.foreach',
    category: '控制与校验',
    icon: 'flow',
    label: '集合遍历',
    description: '逐项执行内联循环体',
    keywords: 'ForEach 循环 遍历 集合 批量',
  },
  {
    id: 'control.repeat',
    category: '控制与校验',
    icon: 'flow',
    label: '重复次数',
    description: '按固定次数执行内联循环体',
    keywords: 'Repeat 循环 次数',
  },
  {
    id: 'control.while',
    category: '控制与校验',
    icon: 'flow',
    label: '条件循环',
    description: '条件为真时执行有界循环体',
    keywords: 'While 条件 循环',
  },
  {
    id: 'control.do_while',
    category: '控制与校验',
    icon: 'flow',
    label: '先执行后判断',
    description: '先执行一次，再判断是否继续',
    keywords: 'DoWhile 循环',
  },
  {
    id: 'control.until',
    category: '控制与校验',
    icon: 'flow',
    label: '直到满足条件',
    description: '条件满足时退出有界循环',
    keywords: 'Until 循环',
  },
  {
    id: 'control.parallel',
    category: '控制与校验',
    icon: 'control',
    label: '并行执行',
    description: '并发运行两个隔离分支并汇合',
    keywords: 'Parallel 并行 分支',
  },
  {
    id: 'control.try',
    category: '控制与校验',
    icon: 'control',
    label: '异常处理',
    description: '运行 Try、匹配 Catch 并执行 Finally',
    keywords: 'Try Catch Finally 清理',
  },
  {
    id: 'control.group',
    category: '控制与校验',
    icon: 'flow',
    label: '步骤组',
    description: '在单一作用域内组织多个步骤',
    keywords: 'Group 步骤组',
  },
  {
    id: 'control.fail',
    category: '控制与校验',
    icon: 'end',
    label: '主动失败',
    description: '用指定错误码结束当前路径',
    keywords: 'Fail 失败 结束',
  },
  {
    id: 'control.return',
    category: '控制与校验',
    icon: 'end',
    label: '返回调用方',
    description: '仅被子流程调用时结束当前调用；直接运行会失败',
    keywords: 'Return 返回 结束 输出',
  },
  {
    id: 'dataset',
    category: '数据与存储',
    icon: 'data',
    label: '数据集',
    description: '读取已上传的数据文件驱动流程',
    keywords: '数据集 文件 dataset CSV JSON',
    prerequisite: '需要已上传数据集',
  },
  {
    id: 'sql',
    category: '数据与存储',
    icon: 'data',
    label: '只读 SQL',
    description: '使用数据库凭据执行参数化只读查询',
    keywords: 'SQL database PostgreSQL MySQL 查询',
    prerequisite: '需要数据库凭据',
  },
  {
    id: 'redis',
    category: '数据与存储',
    icon: 'data',
    label: 'Redis 读取',
    description: '使用 Redis 凭据执行安全只读命令',
    keywords: 'Redis GET HGET 缓存',
    prerequisite: '需要 Redis 凭据',
  },
  {
    id: 'subflow',
    category: '流程复用',
    icon: 'flow',
    label: '子流程',
    description: '调用另一个流程的固定发布版本',
    keywords: '子流程 subflow reuse 复用',
    prerequisite: '需要已发布子流程',
  },
  {
    id: 'for_each',
    category: '流程复用',
    icon: 'flow',
    label: 'ForEach',
    description: '遍历集合并调用固定版本子流程；旧流程保持原语义',
    keywords: 'ForEach 循环 遍历 子流程',
    prerequisite: '需要已发布子流程',
  },
]

export function nodeRegistryItem(id: NodeRegistryKey): NodeRegistryItem {
  const item = nodeRegistry.find((candidate) => candidate.id === id)
  if (!item) throw new Error(`Unknown workflow node registry key: ${id}`)
  return item
}
