import { DeleteOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Empty, Input, InputNumber, Select, Space, Typography } from 'antd'
import type { ReactNode } from 'react'

import type {
  ApiDefinition,
  Artifact,
  WorkflowDefinition,
  WorkflowEdge,
  WorkflowFieldMapping,
  WorkflowNode,
} from '../lib/api'

type InspectorProps = {
  node: WorkflowNode | null
  definition: WorkflowDefinition
  apis: ApiDefinition[]
  artifacts: Artifact[]
  editable: boolean
  onChange: (definition: WorkflowDefinition) => void
  onDelete: () => void
}

export default function WorkflowNodeInspector({
  node,
  definition,
  apis,
  artifacts,
  editable,
  onChange,
  onDelete,
}: InspectorProps) {
  if (!node) return <EmptyInspector />
  const updateNode = (updated: WorkflowNode) => onChange(replaceNode(definition, updated))
  return (
    <aside className="workflow-inspector">
      <Typography.Title level={5}>节点配置</Typography.Title>
      <Field label="名称">
        <Input
          disabled={!editable}
          value={node.name}
          onChange={(event) => updateNode({ ...node, name: event.target.value })}
        />
      </Field>
      <NodeTypeFields
        node={node}
        definition={definition}
        apis={apis}
        artifacts={artifacts}
        editable={editable}
        onUpdate={updateNode}
      />
      {node.type === 'api' && (
        <MappingFields
          node={node}
          definition={definition}
          editable={editable}
          onChange={onChange}
        />
      )}
      <Button
        danger
        icon={<DeleteOutlined />}
        disabled={!editable || node.type === 'start'}
        onClick={onDelete}
      >
        删除节点
      </Button>
    </aside>
  )
}

function EmptyInspector() {
  return (
    <aside className="workflow-inspector">
      <Typography.Title level={5}>节点配置</Typography.Title>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个节点进行配置" />
    </aside>
  )
}

function NodeTypeFields({
  node,
  definition,
  apis,
  artifacts,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  definition: WorkflowDefinition
  apis: ApiDefinition[]
  artifacts: Artifact[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  if (node.type === 'api') {
    return <ApiFields node={node} apis={apis} editable={editable} onUpdate={onUpdate} />
  }
  if (node.type === 'extract') {
    return (
      <>
        <SourceAndExpression
          node={node}
          definition={definition}
          editable={editable}
          onUpdate={onUpdate}
        />
        <TextConfig
          label="保存为变量"
          configKey="variable"
          fallback="extracted_value"
          node={node}
          editable={editable}
          onUpdate={onUpdate}
        />
      </>
    )
  }
  if (node.type === 'assert' || node.type === 'condition') {
    return (
      <>
        <SourceAndExpression
          node={node}
          definition={definition}
          editable={editable}
          onUpdate={onUpdate}
        />
        <Field label="比较运算">
          <Select
            disabled={!editable}
            value={stringConfig(node, 'operator', 'equals')}
            options={comparisonOptions}
            onChange={(value) => onUpdate(updateNodeConfig(node, 'operator', value))}
          />
        </Field>
        <Field label="期望值（JSON 或文本）">
          <Input
            disabled={!editable}
            value={displayExpected(node.config.expected)}
            onChange={(event) =>
              onUpdate(updateNodeConfig(node, 'expected', parseExpected(event.target.value)))
            }
          />
        </Field>
      </>
    )
  }
  if (node.type === 'delay') {
    return (
      <Field label="等待秒数">
        <InputNumber
          disabled={!editable}
          min={0}
          max={300}
          step={0.1}
          value={numberConfig(node, 'seconds', 1)}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'seconds', value ?? 0))}
        />
      </Field>
    )
  }
  if (node.type === 'dataset') {
    return (
      <>
        <Field label="数据文件">
          <Select
            showSearch
            optionFilterProp="label"
            disabled={!editable}
            value={stringConfig(node, 'artifact_id') || undefined}
            placeholder="选择已上传文件"
            options={artifacts.map((artifact) => ({
              value: artifact.id,
              label: `${artifact.filename} · ${formatBytes(artifact.size_bytes)}`,
            }))}
            onChange={(value) => onUpdate(updateNodeConfig(node, 'artifact_id', value))}
          />
        </Field>
        <Field label="文件格式">
          <Select
            disabled={!editable}
            value={stringConfig(node, 'format', 'auto')}
            options={[
              { value: 'auto', label: '自动识别' },
              { value: 'csv', label: 'CSV' },
              { value: 'json', label: 'JSON' },
              { value: 'excel', label: 'Excel' },
            ]}
            onChange={(value) => onUpdate(updateNodeConfig(node, 'format', value))}
          />
        </Field>
        <TextConfig
          label="Excel Sheet（可选）"
          configKey="sheet_name"
          fallback=""
          node={node}
          editable={editable}
          onUpdate={onUpdate}
        />
      </>
    )
  }
  return null
}

function ApiFields({
  node,
  apis,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  apis: ApiDefinition[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <>
      <Field label="接口">
        <Select
          disabled={!editable}
          value={stringConfig(node, 'api_definition_id') || undefined}
          options={apis.map((api) => ({ label: api.name, value: api.id }))}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'api_definition_id', value))}
        />
      </Field>
      <Field label="超时（秒）">
        <InputNumber
          disabled={!editable}
          min={1}
          max={300}
          value={numberConfig(node, 'timeout_seconds', 30)}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'timeout_seconds', value ?? 30))}
        />
      </Field>
      <Field label="最大重试次数">
        <InputNumber
          disabled={!editable}
          min={0}
          max={3}
          value={numberConfig(node, 'max_retries', 0)}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'max_retries', value ?? 0))}
        />
      </Field>
    </>
  )
}

function SourceAndExpression({
  node,
  definition,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  definition: WorkflowDefinition
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  const sources = upstreamNodes(definition, node.id)
  return (
    <>
      <Field label="数据源节点">
        <Select
          disabled={!editable}
          value={stringConfig(node, 'source_node_id') || undefined}
          placeholder="先连接上游节点"
          options={sources.map((source) => ({ value: source.id, label: source.name }))}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'source_node_id', value))}
        />
      </Field>
      <TextConfig
        label="JMESPath 表达式"
        configKey="expression"
        fallback="body"
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
    </>
  )
}

function MappingFields({
  node,
  definition,
  editable,
  onChange,
}: {
  node: WorkflowNode
  definition: WorkflowDefinition
  editable: boolean
  onChange: (definition: WorkflowDefinition) => void
}) {
  const incoming = definition.edges.filter((edge) => edge.target === node.id)
  return (
    <section className="mapping-section">
      <Space className="mapping-heading">
        <Typography.Text strong>入站字段映射</Typography.Text>
        <Button
          size="small"
          type="text"
          icon={<PlusOutlined />}
          disabled={!editable || incoming.length === 0}
          onClick={() => {
            const edge = incoming.at(0)
            if (edge) onChange(replaceEdge(definition, addMapping(edge)))
          }}
        >
          添加
        </Button>
      </Space>
      {incoming.flatMap((edge) =>
        edge.mappings.map((mapping, index) => (
          <MappingEditor
            key={`${edge.id}-${index}`}
            mapping={mapping}
            editable={editable}
            onUpdate={(updated) =>
              onChange(replaceEdge(definition, replaceMapping(edge, index, updated)))
            }
            onDelete={() => onChange(replaceEdge(definition, removeMapping(edge, index)))}
          />
        )),
      )}
      {incoming.length === 0 && (
        <Typography.Text type="secondary">连接上游节点后可映射</Typography.Text>
      )}
    </section>
  )
}

function MappingEditor({
  mapping,
  editable,
  onUpdate,
  onDelete,
}: {
  mapping: WorkflowFieldMapping
  editable: boolean
  onUpdate: (mapping: WorkflowFieldMapping) => void
  onDelete: () => void
}) {
  return (
    <div className="mapping-editor">
      <Input
        aria-label="映射源表达式"
        disabled={!editable}
        placeholder="源 JMESPath"
        value={mapping.source.path}
        onChange={(event) =>
          onUpdate({ ...mapping, source: { ...mapping.source, path: event.target.value } })
        }
      />
      <Select
        aria-label="映射目标位置"
        disabled={!editable}
        value={mapping.target.location}
        options={[
          { value: 'query', label: 'Query' },
          { value: 'header', label: 'Header' },
          { value: 'body', label: 'Body' },
          { value: 'variable', label: 'Variable' },
        ]}
        onChange={(value) =>
          onUpdate({ ...mapping, target: { ...mapping.target, location: value } })
        }
      />
      <Input
        aria-label="映射目标字段"
        disabled={!editable}
        placeholder="目标字段"
        value={mapping.target.key}
        onChange={(event) =>
          onUpdate({ ...mapping, target: { ...mapping.target, key: event.target.value } })
        }
      />
      <Button
        danger
        type="text"
        aria-label="删除映射"
        icon={<MinusCircleOutlined />}
        disabled={!editable}
        onClick={onDelete}
      />
    </div>
  )
}

function TextConfig({
  label,
  configKey,
  fallback,
  node,
  editable,
  onUpdate,
}: {
  label: string
  configKey: string
  fallback: string
  node: WorkflowNode
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <Field label={label}>
      <Input
        disabled={!editable}
        value={stringConfig(node, configKey, fallback)}
        onChange={(event) => onUpdate(updateNodeConfig(node, configKey, event.target.value))}
      />
    </Field>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label>
      <span>{label}</span>
      {children}
    </label>
  )
}

function addMapping(edge: WorkflowEdge): WorkflowEdge {
  return {
    ...edge,
    mappings: [
      ...edge.mappings,
      {
        source: { node_id: edge.source, path: 'body' },
        transform: { kind: 'identity', template: '{{value}}' },
        target: { node_id: edge.target, location: 'body', key: 'value' },
      },
    ],
  }
}

function replaceMapping(
  edge: WorkflowEdge,
  index: number,
  replacement: WorkflowFieldMapping,
): WorkflowEdge {
  return {
    ...edge,
    mappings: edge.mappings.map((mapping, mappingIndex) =>
      mappingIndex === index ? replacement : mapping,
    ),
  }
}

function removeMapping(edge: WorkflowEdge, index: number): WorkflowEdge {
  return { ...edge, mappings: edge.mappings.filter((_mapping, itemIndex) => itemIndex !== index) }
}

function replaceEdge(definition: WorkflowDefinition, replacement: WorkflowEdge) {
  return {
    ...definition,
    edges: definition.edges.map((edge) => (edge.id === replacement.id ? replacement : edge)),
  }
}

function replaceNode(definition: WorkflowDefinition, replacement: WorkflowNode) {
  return {
    ...definition,
    nodes: definition.nodes.map((node) => (node.id === replacement.id ? replacement : node)),
  }
}

function updateNodeConfig(node: WorkflowNode, key: string, value: unknown): WorkflowNode {
  return { ...node, config: { ...node.config, [key]: value } }
}

function upstreamNodes(definition: WorkflowDefinition, targetId: string): WorkflowNode[] {
  const incoming = new Map<string, string[]>()
  for (const edge of definition.edges) {
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source])
  }
  const result = new Set<string>()
  const pending = [...(incoming.get(targetId) ?? [])]
  while (pending.length) {
    const current = pending.pop()
    if (!current || result.has(current)) continue
    result.add(current)
    pending.push(...(incoming.get(current) ?? []))
  }
  return definition.nodes.filter((node) => result.has(node.id))
}

function stringConfig(node: WorkflowNode, key: string, fallback = ''): string {
  const value = node.config[key]
  return typeof value === 'string' ? value : fallback
}

function numberConfig(node: WorkflowNode, key: string, fallback: number): number {
  const value = node.config[key]
  return typeof value === 'number' ? value : fallback
}

function parseExpected(value: string): unknown {
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

function displayExpected(value: unknown): string {
  if (typeof value === 'string') return value
  return value === undefined ? '' : JSON.stringify(value)
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  return `${(value / 1024).toFixed(1)} KB`
}

const comparisonOptions = [
  { value: 'equals', label: '等于' },
  { value: 'not_equals', label: '不等于' },
  { value: 'contains', label: '包含' },
  { value: 'exists', label: '存在' },
  { value: 'greater_than', label: '大于' },
  { value: 'less_than', label: '小于' },
]
