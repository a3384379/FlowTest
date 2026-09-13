import { Button, Space, Tag, Typography, Alert } from 'antd'
import type { WorkflowDefinition, WorkflowEdge } from '../lib/api'
import MappingEditor from './WorkflowMappingEditor'
import { resolveEffectiveNodeType } from './editor/graph-analysis'

export default function WorkflowEdgeInspector({
  edge,
  definition,
  editable,
  onUpdate,
  onDelete,
  onSwap,
}: {
  edge: WorkflowEdge
  definition: WorkflowDefinition
  editable: boolean
  onUpdate: (edge: WorkflowEdge) => void
  onDelete: () => void
  onSwap: () => void
}) {
  const source = definition.nodes.find((node) => node.id === edge.source)
  const target = definition.nodes.find((node) => node.id === edge.target)
  const supportsMapping = supportsRequestMapping(target)
  return (
    <aside className="workflow-inspector">
      <Typography.Title level={5}>连线配置</Typography.Title>
      <Space orientation="vertical" className="full-width">
        <Typography.Text>源节点：{source?.name ?? edge.source}</Typography.Text>
        <Typography.Text type="secondary">{edge.source}</Typography.Text>
        <Typography.Text>目标节点：{target?.name ?? edge.target}</Typography.Text>
        <Typography.Text type="secondary">{edge.target}</Typography.Text>
        <Tag>
          {edge.condition == null
            ? '普通连接'
            : edge.condition === 'true'
              ? '条件为真'
              : '条件为假'}
        </Tag>
        {edge.condition != null && (
          <>
            <Typography.Text type="secondary">比较规则在条件节点中配置。</Typography.Text>
            <Button disabled={!editable} onClick={onSwap}>
              交换真假分支
            </Button>
          </>
        )}
        <Typography.Text strong>字段映射（{edge.mappings.length}）</Typography.Text>
        {!supportsMapping && (
          <Alert type="info" title="目标节点不支持请求参数映射编辑，已有映射保持原样。" />
        )}
        {edge.mappings.map((mapping, index) => (
          <MappingEditor
            key={index}
            mapping={mapping}
            editable={editable && Boolean(supportsMapping)}
            onUpdate={(updated) =>
              onUpdate({
                ...edge,
                mappings: edge.mappings.map((item, i) => (i === index ? updated : item)),
              })
            }
            onDelete={() =>
              onUpdate({ ...edge, mappings: edge.mappings.filter((_, i) => i !== index) })
            }
          />
        ))}
        <Button
          disabled={!editable || !supportsMapping}
          onClick={() =>
            onUpdate({
              ...edge,
              mappings: [
                ...edge.mappings,
                {
                  source: { node_id: edge.source, path: 'body' },
                  transform: { kind: 'identity', template: '{{value}}' },
                  target: { node_id: edge.target, location: 'body', key: 'value' },
                },
              ],
            })
          }
        >
          添加映射
        </Button>
        <Button danger disabled={!editable} onClick={onDelete}>
          删除连线
        </Button>
        <Typography.Text type="secondary">删除后可撤销，字段映射会一并恢复。</Typography.Text>
      </Space>
    </aside>
  )
}

function supportsRequestMapping(node: import('../lib/api').WorkflowNode | undefined): boolean {
  return Boolean(node && resolveEffectiveNodeType(node) === 'api')
}
