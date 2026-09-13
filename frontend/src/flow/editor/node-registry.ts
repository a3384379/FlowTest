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
    description: '遍历集合并调用固定版本子流程',
    keywords: 'ForEach 循环 遍历 子流程',
    prerequisite: '需要已发布子流程',
  },
]

export function nodeRegistryItem(id: NodeRegistryKey): NodeRegistryItem {
  const item = nodeRegistry.find((candidate) => candidate.id === id)
  if (!item) throw new Error(`Unknown workflow node registry key: ${id}`)
  return item
}
