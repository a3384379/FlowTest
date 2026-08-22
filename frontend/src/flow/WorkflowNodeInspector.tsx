import { DeleteOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Empty, Input, InputNumber, Select, Space, Typography } from 'antd'
import type { ReactNode } from 'react'

import type {
  ApiDefinition,
  Artifact,
  Credential,
  Workflow,
  WorkflowDefinition,
  WorkflowEdge,
  WorkflowFieldMapping,
  WorkflowNode,
} from '../lib/api'
import type { EventSource, SchemaArtifact } from '../features/protocols/protocol-service'
import WorkflowApiRequestEditor from './WorkflowApiRequestEditor'

type InspectorProps = {
  projectId?: string | null
  environmentId?: string | null
  node: WorkflowNode | null
  definition: WorkflowDefinition
  apis: ApiDefinition[]
  artifacts: Artifact[]
  workflows?: Workflow[]
  credentials: Credential[]
  graphqlSchemas?: SchemaArtifact[]
  grpcDescriptors?: SchemaArtifact[]
  eventSources?: EventSource[]
  editable: boolean
  onChange: (definition: WorkflowDefinition) => void
  onDelete: () => void
}

export default function WorkflowNodeInspector({
  projectId,
  environmentId,
  node,
  definition,
  apis,
  artifacts,
  workflows = [],
  credentials,
  graphqlSchemas = [],
  grpcDescriptors = [],
  eventSources = [],
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
      <InspectorNodeFields
        node={node}
        definition={definition}
        apis={apis}
        artifacts={artifacts}
        workflows={workflows}
        credentials={credentials}
        graphqlSchemas={graphqlSchemas}
        grpcDescriptors={grpcDescriptors}
        eventSources={eventSources}
        projectId={projectId}
        environmentId={environmentId}
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

function InspectorNodeFields({
  projectId,
  environmentId,
  node,
  definition,
  apis,
  artifacts,
  workflows,
  credentials,
  graphqlSchemas,
  grpcDescriptors,
  eventSources,
  editable,
  onUpdate,
}: Omit<InspectorProps, 'node' | 'onChange' | 'onDelete'> & {
  node: WorkflowNode
  workflows: Workflow[]
  graphqlSchemas: SchemaArtifact[]
  grpcDescriptors: SchemaArtifact[]
  eventSources: EventSource[]
  onUpdate: (node: WorkflowNode) => void
}) {
  if (isEventCapability(node)) {
    return (
      <EventCapabilityFields
        node={node}
        definition={definition}
        eventSources={eventSources}
        editable={editable}
        onUpdate={onUpdate}
      />
    )
  }
  if (isProtocolCapability(node)) {
    return (
      <ProtocolCapabilityFields
        node={node}
        definition={definition}
        graphqlSchemas={graphqlSchemas}
        grpcDescriptors={grpcDescriptors}
        credentials={credentials}
        editable={editable}
        onUpdate={onUpdate}
      />
    )
  }
  if (node.type === 'sql' || node.type === 'redis') {
    return (
      <DataNodeFields
        node={node}
        credentials={credentials}
        editable={editable}
        onUpdate={onUpdate}
      />
    )
  }
  return (
    <NodeTypeFields
      node={node}
      definition={definition}
      apis={apis}
      artifacts={artifacts}
      projectId={projectId}
      environmentId={environmentId}
      workflows={workflows}
      editable={editable}
      onUpdate={onUpdate}
    />
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
  projectId,
  environmentId,
  node,
  definition,
  apis,
  artifacts,
  workflows,
  editable,
  onUpdate,
}: {
  projectId?: string | null
  environmentId?: string | null
  node: WorkflowNode
  definition: WorkflowDefinition
  apis: ApiDefinition[]
  artifacts: Artifact[]
  workflows: Workflow[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  if (node.type === 'api') {
    return (
      <ApiFields
        projectId={projectId}
        environmentId={environmentId}
        node={node}
        apis={apis}
        artifacts={artifacts}
        editable={editable}
        onUpdate={onUpdate}
      />
    )
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
  if (node.type === 'subflow' || node.type === 'for_each') {
    return (
      <SubflowFields
        node={node}
        definition={definition}
        workflows={workflows}
        editable={editable}
        onUpdate={onUpdate}
      />
    )
  }
  return null
}

function SubflowFields({
  node,
  definition,
  workflows,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  definition: WorkflowDefinition
  workflows: Workflow[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <>
      <Field label="已发布子流程">
        <Select
          showSearch
          optionFilterProp="label"
          disabled={!editable}
          value={stringConfig(node, 'workflow_id') || undefined}
          options={workflows.map((workflow) => ({
            value: workflow.id,
            label: `${workflow.name} · v${workflow.current_version}`,
          }))}
          onChange={(value) => {
            const selected = workflows.find((workflow) => workflow.id === value)
            onUpdate(
              updateNodeConfigs(node, {
                workflow_id: value,
                workflow_version: selected?.current_version ?? 1,
              }),
            )
          }}
        />
      </Field>
      <Field label="固定版本">
        <InputNumber
          disabled={!editable}
          min={1}
          value={numberConfig(node, 'workflow_version', 1)}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'workflow_version', value ?? 1))}
        />
      </Field>
      {node.type === 'for_each' && (
        <ForEachFields
          node={node}
          definition={definition}
          editable={editable}
          onUpdate={onUpdate}
        />
      )}
    </>
  )
}

function DataNodeFields({
  node,
  credentials,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  credentials: Credential[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  const compatible = credentials.filter((credential) =>
    node.type === 'redis'
      ? credential.kind === 'redis'
      : credential.kind === 'postgresql' || credential.kind === 'mysql',
  )
  return (
    <>
      <Field label="Credential">
        <Select
          disabled={!editable}
          value={stringConfig(node, 'credential_id') || undefined}
          placeholder="选择只读 Credential"
          options={compatible.map((credential) => ({
            value: credential.id,
            label: `${credential.name} · ${credential.host}:${credential.port}`,
          }))}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'credential_id', value))}
        />
      </Field>
      {node.type === 'sql' ? (
        <>
          <Field label="单条只读查询">
            <Input.TextArea
              className="code-input"
              rows={6}
              disabled={!editable}
              value={stringConfig(node, 'query', 'SELECT 1 AS healthy')}
              onChange={(event) => onUpdate(updateNodeConfig(node, 'query', event.target.value))}
            />
          </Field>
          <JsonConfig
            label="查询参数（JSON）"
            configKey="parameters"
            fallback={{}}
            node={node}
            editable={editable}
            onUpdate={onUpdate}
          />
        </>
      ) : (
        <>
          <Field label="只读命令">
            <Select
              disabled={!editable}
              value={stringConfig(node, 'command', 'GET')}
              options={[
                'GET',
                'MGET',
                'HGET',
                'HGETALL',
                'SMEMBERS',
                'ZRANGE',
                'EXISTS',
                'TTL',
              ].map((value) => ({ value, label: value }))}
              onChange={(value) => onUpdate(updateNodeConfig(node, 'command', value))}
            />
          </Field>
          <JsonConfig
            label="命令参数（JSON 数组）"
            configKey="arguments"
            fallback={['key']}
            node={node}
            editable={editable}
            onUpdate={onUpdate}
          />
        </>
      )}
      <Field label="超时（秒）">
        <InputNumber
          disabled={!editable}
          min={1}
          max={30}
          value={numberConfig(node, 'timeout_seconds', 30)}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'timeout_seconds', value ?? 30))}
        />
      </Field>
      <Typography.Paragraph type="secondary">
        SQL 仅允许参数化 SELECT；Redis 仅允许 GET/MGET/HGET/HGETALL/SMEMBERS/ZRANGE/EXISTS/TTL。
      </Typography.Paragraph>
    </>
  )
}

function ProtocolCapabilityFields({
  node,
  definition,
  graphqlSchemas,
  grpcDescriptors,
  credentials,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  definition: WorkflowDefinition
  graphqlSchemas: SchemaArtifact[]
  grpcDescriptors: SchemaArtifact[]
  credentials: Credential[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <>
      {node.capability_id === 'graphql.request' ? (
        <GraphQLCapabilityFields
          node={node}
          schemas={graphqlSchemas}
          editable={editable}
          onUpdate={onUpdate}
        />
      ) : (
        <GrpcCapabilityFields
          node={node}
          descriptors={grpcDescriptors}
          credentials={credentials}
          editable={editable}
          onUpdate={onUpdate}
        />
      )}
      <CapabilityBindingFields
        node={node}
        definition={definition}
        editable={editable}
        onUpdate={onUpdate}
      />
    </>
  )
}

function EventCapabilityFields({
  node,
  definition,
  eventSources,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  definition: WorkflowDefinition
  eventSources: EventSource[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  const kafka = node.capability_id?.startsWith('kafka.') === true
  const compatibleSources = eventSources.filter((source) =>
    kafka ? source.kind === 'kafka' : source.kind === 'websocket',
  )
  return (
    <>
      <Field label="固定事件源版本">
        <Select
          disabled={!editable}
          value={capabilityString(node, 'source_id') || undefined}
          options={compatibleSources.map((source) => ({
            value: source.id,
            label: `${source.name} · v${source.version}`,
          }))}
          onChange={(value) => onUpdate(updateCapabilityConfig(node, 'source_id', value))}
        />
      </Field>
      {kafka ? (
        <>
          <CapabilityText
            label="Topic"
            configKey="topic"
            node={node}
            editable={editable}
            onUpdate={onUpdate}
          />
          {node.capability_id === 'kafka.produce' ? (
            <CapabilityJson
              label="Message（JSON）"
              configKey="value"
              fallback={{}}
              node={node}
              editable={editable}
              onUpdate={onUpdate}
            />
          ) : (
            <>
              <Field label="起始 Offset">
                <Select
                  disabled={!editable}
                  value={capabilityString(node, 'offset', 'latest')}
                  options={[
                    { value: 'latest', label: 'Latest' },
                    { value: 'earliest', label: 'Earliest' },
                  ]}
                  onChange={(value) => onUpdate(updateCapabilityConfig(node, 'offset', value))}
                />
              </Field>
              <Field label="最多消费消息">
                <InputNumber
                  disabled={!editable}
                  min={1}
                  max={1000}
                  value={capabilityNumber(node, 'maximum_messages', 10)}
                  onChange={(value) =>
                    onUpdate(updateCapabilityConfig(node, 'maximum_messages', value ?? 1))
                  }
                />
              </Field>
            </>
          )}
          <CapabilityText
            label="固定 Schema ID（可选）"
            configKey="schema_id"
            node={node}
            editable={editable}
            onUpdate={onUpdate}
          />
        </>
      ) : (
        <>
          <Field label="Payload 类型">
            <Select
              disabled={!editable}
              value={capabilityString(node, 'payload_kind', 'json')}
              options={[
                { value: 'json', label: 'JSON' },
                { value: 'text', label: 'Text' },
              ]}
              onChange={(value) => onUpdate(updateCapabilityConfig(node, 'payload_kind', value))}
            />
          </Field>
          <CapabilityJson
            label="Message（JSON）"
            configKey="message"
            fallback={{}}
            node={node}
            editable={editable}
            onUpdate={onUpdate}
          />
          <CapabilityText
            label="Correlation JMESPath（可选）"
            configKey="correlation_expression"
            node={node}
            editable={editable}
            onUpdate={onUpdate}
          />
        </>
      )}
      <CapabilityTimeout node={node} editable={editable} onUpdate={onUpdate} />
      <CapabilityBindingFields
        node={node}
        definition={definition}
        editable={editable}
        onUpdate={onUpdate}
      />
    </>
  )
}

function GraphQLCapabilityFields({
  node,
  schemas,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  schemas: SchemaArtifact[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <>
      <Field label="固定 Schema 版本">
        <Select
          disabled={!editable}
          value={capabilityString(node, 'schema_id') || undefined}
          options={schemas.map((schema) => ({
            value: schema.id,
            label: `${schema.name} · v${schema.version}`,
          }))}
          onChange={(value) => onUpdate(updateCapabilityConfig(node, 'schema_id', value))}
        />
      </Field>
      <CapabilityText
        label="GraphQL Endpoint"
        configKey="endpoint"
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <CapabilityTextArea
        label="Query / Mutation"
        configKey="operation"
        rows={8}
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <CapabilityJson
        label="Variables（JSON）"
        configKey="variables"
        fallback={{}}
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <CapabilityJson
        label="Headers（JSON）"
        configKey="headers"
        fallback={{}}
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <CapabilityTimeout node={node} editable={editable} onUpdate={onUpdate} />
    </>
  )
}

function GrpcCapabilityFields({
  node,
  descriptors,
  credentials,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  descriptors: SchemaArtifact[]
  credentials: Credential[]
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  const descriptor = descriptors.find((item) => item.id === capabilityString(node, 'descriptor_id'))
  const methods = grpcMethods(descriptor)
  const tlsMode = capabilityString(node, 'tls_mode', 'plaintext')
  return (
    <>
      <Field label="固定 Descriptor 版本">
        <Select
          disabled={!editable}
          value={descriptor?.id}
          options={descriptors.map((item) => ({
            value: item.id,
            label: `${item.name} · v${item.version}`,
          }))}
          onChange={(value) => onUpdate(selectGrpcDescriptor(node, descriptors, value))}
        />
      </Field>
      <CapabilityText
        label="gRPC Endpoint"
        configKey="endpoint"
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <Field label="Service / Method">
        <Select
          showSearch
          optionFilterProp="label"
          disabled={!editable}
          value={grpcMethodValue(node)}
          options={methods.map((method) => ({
            value: `${method.service}/${method.method}`,
            label: `${method.service} / ${method.method} · ${method.callType}`,
          }))}
          onChange={(value) => onUpdate(selectGrpcMethod(node, methods, value))}
        />
      </Field>
      <CapabilityJson
        label="Request（JSON）"
        configKey="request"
        fallback={{}}
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <CapabilityJson
        label="Metadata（JSON）"
        configKey="metadata"
        fallback={{}}
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <Field label="传输安全">
        <Select
          disabled={!editable}
          value={tlsMode}
          options={[
            { value: 'plaintext', label: 'Plaintext' },
            { value: 'tls', label: 'TLS' },
            { value: 'mtls', label: 'mTLS' },
          ]}
          onChange={(value) => onUpdate(updateGrpcTls(node, value))}
        />
      </Field>
      {tlsMode === 'mtls' && (
        <Field label="mTLS Credential">
          <Select
            disabled={!editable}
            value={capabilityString(node, 'credential_id') || undefined}
            options={credentials
              .filter((credential) => credential.kind === 'grpc_mtls')
              .map((credential) => ({ value: credential.id, label: credential.name }))}
            onChange={(value) => onUpdate(updateCapabilityConfig(node, 'credential_id', value))}
          />
        </Field>
      )}
      <CapabilityTimeout node={node} editable={editable} onUpdate={onUpdate} />
    </>
  )
}

function CapabilityBindingFields({
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
  const bindings = node.bindings ?? []
  const sources = upstreamNodes(definition, node.id)
  const defaultTarget = capabilityBindingTarget(node.capability_id)
  return (
    <section className="mapping-section">
      <Space className="mapping-heading">
        <Typography.Text strong>结构化数据绑定</Typography.Text>
        <Button
          size="small"
          type="text"
          icon={<PlusOutlined />}
          disabled={!editable || sources.length === 0}
          onClick={() =>
            onUpdate({
              ...node,
              bindings: [
                ...bindings,
                {
                  input: defaultTarget,
                  expression: `node_outputs.${sources.at(-1)?.id ?? 'source'}.body`,
                },
              ],
            })
          }
        >
          添加
        </Button>
      </Space>
      {bindings.map((binding, index) => (
        <div className="mapping-editor" key={`${node.id}-binding-${index}`}>
          <Input
            aria-label="Capability 绑定源"
            disabled={!editable}
            value={binding.expression}
            placeholder="node_outputs.login.body.token"
            onChange={(event) =>
              onUpdate(replaceCapabilityBinding(node, index, 'expression', event.target.value))
            }
          />
          <Input
            aria-label="Capability 绑定目标"
            disabled={!editable}
            value={binding.input}
            placeholder={defaultTarget}
            onChange={(event) =>
              onUpdate(replaceCapabilityBinding(node, index, 'input', event.target.value))
            }
          />
          <Button
            danger
            type="text"
            aria-label="删除 Capability 绑定"
            icon={<MinusCircleOutlined />}
            disabled={!editable}
            onClick={() =>
              onUpdate({
                ...node,
                bindings: bindings.filter((_item, itemIndex) => itemIndex !== index),
              })
            }
          />
        </div>
      ))}
      {!bindings.length && (
        <Typography.Text type="secondary">连接上游节点后可绑定响应字段</Typography.Text>
      )}
    </section>
  )
}

function capabilityBindingTarget(capabilityId: string | null | undefined): string {
  if (capabilityId === 'graphql.request') return 'variables.value'
  if (capabilityId === 'kafka.produce') return 'value.id'
  if (capabilityId === 'kafka.consume') return 'correlation_id'
  if (capabilityId?.startsWith('websocket.')) return 'message.id'
  return 'request.value'
}

function CapabilityText({
  label,
  configKey,
  node,
  editable,
  onUpdate,
}: {
  label: string
  configKey: string
  node: WorkflowNode
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <Field label={label}>
      <Input
        disabled={!editable}
        value={capabilityString(node, configKey)}
        onChange={(event) => onUpdate(updateCapabilityConfig(node, configKey, event.target.value))}
      />
    </Field>
  )
}

function CapabilityTextArea({
  label,
  configKey,
  rows,
  node,
  editable,
  onUpdate,
}: {
  label: string
  configKey: string
  rows: number
  node: WorkflowNode
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <Field label={label}>
      <Input.TextArea
        className="code-input"
        rows={rows}
        disabled={!editable}
        value={capabilityString(node, configKey)}
        onChange={(event) => onUpdate(updateCapabilityConfig(node, configKey, event.target.value))}
      />
    </Field>
  )
}

function CapabilityJson({
  label,
  configKey,
  fallback,
  node,
  editable,
  onUpdate,
}: {
  label: string
  configKey: string
  fallback: unknown
  node: WorkflowNode
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  const value = node.configuration?.[configKey] ?? fallback
  return (
    <Field label={label}>
      <Input.TextArea
        key={`${node.id}-${configKey}-${JSON.stringify(value)}`}
        className="code-input"
        rows={3}
        disabled={!editable}
        defaultValue={JSON.stringify(value, null, 2)}
        onBlur={(event) => {
          const parsed = parseJsonInput(event.target.value)
          if (parsed !== undefined) onUpdate(updateCapabilityConfig(node, configKey, parsed))
        }}
      />
    </Field>
  )
}

function CapabilityTimeout({
  node,
  editable,
  onUpdate,
}: {
  node: WorkflowNode
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <Field label="超时（秒）">
      <InputNumber
        disabled={!editable}
        min={1}
        max={300}
        value={capabilityNumber(node, 'timeout_seconds', 30)}
        onChange={(value) => onUpdate(updateCapabilityConfig(node, 'timeout_seconds', value ?? 30))}
      />
    </Field>
  )
}

type GrpcMethodOption = {
  service: string
  method: string
  callType: 'unary' | 'server_streaming'
}

function grpcMethods(descriptor: SchemaArtifact | undefined): GrpcMethodOption[] {
  const services = Array.isArray(descriptor?.summary.services) ? descriptor.summary.services : []
  return services.flatMap((service) => {
    if (!isRecord(service) || typeof service.name !== 'string' || !Array.isArray(service.methods)) {
      return []
    }
    return service.methods.flatMap((method) =>
      isRecord(method) && typeof method.name === 'string'
        ? [
            {
              service: service.name as string,
              method: method.name,
              callType: method.call_type === 'server_streaming' ? 'server_streaming' : 'unary',
            } satisfies GrpcMethodOption,
          ]
        : [],
    )
  })
}

function selectGrpcDescriptor(
  node: WorkflowNode,
  descriptors: SchemaArtifact[],
  descriptorId: string,
): WorkflowNode {
  const method = grpcMethods(descriptors.find((item) => item.id === descriptorId)).at(0)
  return updateCapabilityConfigs(node, {
    descriptor_id: descriptorId,
    service: method?.service ?? '',
    method: method?.method ?? '',
    call_type: method?.callType ?? 'unary',
  })
}

function selectGrpcMethod(
  node: WorkflowNode,
  methods: GrpcMethodOption[],
  value: string,
): WorkflowNode {
  const method = methods.find((item) => `${item.service}/${item.method}` === value)
  return updateCapabilityConfigs(node, {
    service: method?.service ?? '',
    method: method?.method ?? '',
    call_type: method?.callType ?? 'unary',
  })
}

function grpcMethodValue(node: WorkflowNode): string | undefined {
  const service = capabilityString(node, 'service')
  const method = capabilityString(node, 'method')
  return service && method ? `${service}/${method}` : undefined
}

function updateGrpcTls(node: WorkflowNode, tlsMode: string): WorkflowNode {
  const values: Record<string, unknown> = { tls_mode: tlsMode }
  if (tlsMode !== 'mtls') values.credential_id = undefined
  return updateCapabilityConfigs(node, values)
}

function replaceCapabilityBinding(
  node: WorkflowNode,
  index: number,
  key: 'input' | 'expression',
  value: string,
): WorkflowNode {
  return {
    ...node,
    bindings: (node.bindings ?? []).map((binding, itemIndex) =>
      itemIndex === index ? { ...binding, [key]: value } : binding,
    ),
  }
}

function isProtocolCapability(node: WorkflowNode): boolean {
  return (
    node.type === 'capability' &&
    (node.capability_id === 'graphql.request' || node.capability_id === 'grpc.call')
  )
}

function isEventCapability(node: WorkflowNode): boolean {
  return (
    node.type === 'capability' &&
    [
      'kafka.produce',
      'kafka.consume',
      'websocket.connect',
      'websocket.send',
      'websocket.await',
      'websocket.close',
      'websocket.exchange',
    ].includes(node.capability_id ?? '')
  )
}

function capabilityString(node: WorkflowNode, key: string, fallback = ''): string {
  const value = node.configuration?.[key]
  return typeof value === 'string' ? value : fallback
}

function capabilityNumber(node: WorkflowNode, key: string, fallback: number): number {
  const value = node.configuration?.[key]
  return typeof value === 'number' ? value : fallback
}

function updateCapabilityConfig(node: WorkflowNode, key: string, value: unknown): WorkflowNode {
  return { ...node, configuration: { ...node.configuration, [key]: value } }
}

function updateCapabilityConfigs(
  node: WorkflowNode,
  values: Record<string, unknown>,
): WorkflowNode {
  return { ...node, configuration: { ...node.configuration, ...values } }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function JsonConfig({
  label,
  configKey,
  fallback,
  node,
  editable,
  onUpdate,
}: {
  label: string
  configKey: string
  fallback: unknown
  node: WorkflowNode
  editable: boolean
  onUpdate: (node: WorkflowNode) => void
}) {
  return (
    <Field label={label}>
      <Input.TextArea
        key={`${node.id}-${configKey}-${JSON.stringify(node.config[configKey])}`}
        className="code-input"
        rows={3}
        disabled={!editable}
        defaultValue={JSON.stringify(node.config[configKey] ?? fallback, null, 2)}
        onBlur={(event) => {
          const parsed = parseJsonInput(event.target.value)
          if (parsed !== undefined) onUpdate(updateNodeConfig(node, configKey, parsed))
        }}
      />
    </Field>
  )
}

function parseJsonInput(value: string): unknown | undefined {
  try {
    return JSON.parse(value) as unknown
  } catch (error) {
    if (error instanceof SyntaxError) return undefined
    throw error
  }
}

function ForEachFields({
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
  return (
    <>
      <SourceAndExpression
        node={node}
        definition={definition}
        editable={editable}
        onUpdate={onUpdate}
      />
      <TextConfig
        label="元素变量"
        configKey="item_variable"
        fallback="item"
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <TextConfig
        label="索引变量"
        configKey="index_variable"
        fallback="index"
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <Field label="循环并发">
        <InputNumber
          disabled={!editable}
          min={1}
          max={20}
          value={numberConfig(node, 'concurrency', 5)}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'concurrency', value ?? 5))}
        />
      </Field>
      <Field label="失败策略">
        <Select
          disabled={!editable}
          value={node.config.fail_fast === false ? 'continue' : 'fail_fast'}
          options={[
            { value: 'fail_fast', label: '首项失败即停止' },
            { value: 'continue', label: '继续处理其他项' },
          ]}
          onChange={(value) => onUpdate(updateNodeConfig(node, 'fail_fast', value === 'fail_fast'))}
        />
      </Field>
    </>
  )
}

function ApiFields({
  projectId,
  environmentId,
  node,
  apis,
  artifacts,
  editable,
  onUpdate,
}: {
  projectId?: string | null
  environmentId?: string | null
  node: WorkflowNode
  apis: ApiDefinition[]
  artifacts: Artifact[]
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
          onChange={(value) => {
            const selected = apis.find((api) => api.id === value)
            onUpdate({
              ...node,
              config: {
                ...node.config,
                api_definition_id: value,
                api_version: selected?.current_version,
                request_overrides: {},
              },
            })
          }}
        />
      </Field>
      <TextConfig
        label="Service Override（可选）"
        configKey="service_override"
        fallback=""
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <TextConfig
        label="Endpoint Variant（可选）"
        configKey="endpoint_variant"
        fallback=""
        node={node}
        editable={editable}
        onUpdate={onUpdate}
      />
      <WorkflowApiRequestEditor
        projectId={projectId}
        environmentId={environmentId}
        node={node}
        api={apis.find((api) => api.id === stringConfig(node, 'api_definition_id'))}
        artifacts={artifacts}
        editable={editable}
        onUpdate={onUpdate}
      />
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

function updateNodeConfigs(node: WorkflowNode, values: Record<string, unknown>): WorkflowNode {
  return { ...node, config: { ...node.config, ...values } }
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
