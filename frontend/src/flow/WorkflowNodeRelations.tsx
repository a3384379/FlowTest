import { NodeIndexOutlined } from '@ant-design/icons'
import { Button, Empty, Space, Typography } from 'antd'
import type { WorkflowDefinition, WorkflowNode } from '../lib/api'
import { dataReferences } from './editor/node-presentation'
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
  const updated = {
    ...definition,
    nodes: definition.nodes.map((item) => (item.id === node.id ? node : item)),
  }
  const sources = dataReferences(updated).filter((reference) => reference.target === node.id)
  const config = effectiveConfig(node)
  const outgoing = definition.edges.filter((edge) => edge.source === node.id)
  return (
    <section className="workflow-node-relations">
      <Typography.Title level={5}>数据来源</Typography.Title>
      {sources.map((reference) => (
        <div key={reference.id} className="workflow-source-card">
          <Button
            type="link"
            icon={<NodeIndexOutlined />}
            disabled={!onLocateNode}
            onClick={() => onLocateNode?.(reference.source)}
          >
            {definition.nodes.find((item) => item.id === reference.source)?.name ??
              reference.source}
          </Button>
          <Typography.Text type="secondary">{reference.label}</Typography.Text>
        </div>
      ))}
      {typeof config.expression === 'string' && (
        <Typography.Paragraph code>{config.expression}</Typography.Paragraph>
      )}
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
            {edge.condition === null
              ? ''
              : ` · ${edge.condition === 'true' ? '条件成立' : '条件不成立'}`}
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
