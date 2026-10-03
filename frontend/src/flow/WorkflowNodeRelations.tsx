import { NodeIndexOutlined } from '@ant-design/icons'
import { Button, Empty, Space, Typography } from 'antd'
import type { WorkflowDefinition, WorkflowNode } from '../lib/api'
import { nodeDataSources, referenceNodes, type NodeDataSource } from './editor/node-data-sources'
import { effectiveConfig } from './editor/graph-analysis'

export default function WorkflowNodeRelations({
  node,
  definition,
  onLocateNode,
}: {
  node: WorkflowNode
  definition: WorkflowDefinition
  onLocateNode?: (nodeId: string) => void
}) {
  const updated = withRelationsNode(definition, node)
  const sources = nodeDataSources(updated, node.id)
  const config = effectiveConfig(node)
  const outgoing = [
    ...definition.edges,
    ...(definition.regions ?? []).flatMap((region) => region.edges),
  ].filter((edge) => edge.source === node.id)
  return (
    <section className="workflow-node-relations">
      <Typography.Title level={5}>数据来源</Typography.Title>
      {sources.map((reference) => (
        <DataSourceCard
          key={reference.id}
          source={reference}
          definition={updated}
          onLocateNode={onLocateNode}
        />
      ))}
      {!sources.length && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未配置直接数据引用" />
      )}
      <Typography.Title level={5}>输出与下游</Typography.Title>
      {typeof config.variable === 'string' && (
        <Typography.Paragraph>
          输出变量：<Typography.Text code>{config.variable}</Typography.Text>
        </Typography.Paragraph>
      )}
      <Space orientation="vertical" align="start">
        {outgoing.map((edge) => (
          <Button
            key={edge.id}
            type="link"
            disabled={!onLocateNode}
            onClick={() => onLocateNode?.(edge.target)}
          >
            {definition.nodes.find((item) => item.id === edge.target)?.name ?? edge.target}
            {edge.condition === 'true'
              ? ' · 条件成立分支'
              : edge.condition === 'false'
                ? ' · 条件不成立分支'
                : ''}
          </Button>
        ))}
      </Space>
      {!outgoing.length && <Typography.Text type="secondary">暂无下游执行连线</Typography.Text>}
      <Typography.Paragraph type="secondary">
        这里展示图定义中的引用关系，实际输出在执行后查看。点击来源或下游可定位节点。
      </Typography.Paragraph>
    </section>
  )
}

function withRelationsNode(definition: WorkflowDefinition, node: WorkflowNode): WorkflowDefinition {
  const replace = (item: WorkflowNode) => (item.id === node.id ? node : item)
  return {
    ...definition,
    nodes: definition.nodes.map(replace),
    regions: definition.regions?.map((region) => ({ ...region, nodes: region.nodes.map(replace) })),
  }
}

function DataSourceCard({
  source,
  definition,
  onLocateNode,
}: {
  source: NodeDataSource
  definition: WorkflowDefinition
  onLocateNode?: (nodeId: string) => void
}) {
  return (
    <div className="workflow-source-card" aria-label={`数据来源 ${source.targetPath}`}>
      <SourceOrigin source={source} definition={definition} onLocateNode={onLocateNode} />
      <Typography.Text type="secondary">{source.scope}</Typography.Text>
      <Typography.Text type="secondary">
        {source.expression ? '输出表达式' : '字段路径'}
      </Typography.Text>
      <Typography.Text code>{source.path}</Typography.Text>
      <Typography.Text type="secondary">配置位置</Typography.Text>
      <Typography.Text code>{source.targetPath}</Typography.Text>
      {source.reason && <Typography.Text type="warning">{source.reason}</Typography.Text>}
    </div>
  )
}

function SourceOrigin({
  source,
  definition,
  onLocateNode,
}: {
  source: NodeDataSource
  definition: WorkflowDefinition
  onLocateNode?: (nodeId: string) => void
}) {
  if (!source.sourceId)
    return (
      <Typography.Text strong>
        {source.kind === 'variable' ? '变量引用' : '待核对的表达式'}
      </Typography.Text>
    )
  const name =
    referenceNodes(definition).find((item) => item.id === source.sourceId)?.name ?? source.sourceId
  if (source.reason || !definition.nodes.some((node) => node.id === source.sourceId))
    return <Typography.Text strong>{name}</Typography.Text>
  return (
    <Button
      type="link"
      icon={<NodeIndexOutlined />}
      aria-label={name}
      disabled={!onLocateNode}
      onClick={() => onLocateNode?.(source.sourceId!)}
    >
      {name}
    </Button>
  )
}
