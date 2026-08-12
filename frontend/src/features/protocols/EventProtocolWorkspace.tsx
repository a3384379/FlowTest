import {
  CloudServerOutlined,
  DatabaseOutlined,
  ImportOutlined,
  PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMemo, useState } from 'react'

import {
  consumeKafkaMessages,
  createEventSchema,
  createEventSource,
  exchangeWebSocketMessage,
  importEventRegistrySchema,
  listEventSchemas,
  listEventSources,
  produceKafkaMessage,
  type EventDebugResult,
  type EventSource,
  type SchemaArtifact,
} from './protocol-service'

const { TextArea } = Input

export type EventProtocolMode = 'kafka' | 'websocket'

const EVENT_PRESENTATION: Record<
  EventProtocolMode,
  { color: string; label: string; boundary: string; supportsSchema: boolean }
> = {
  kafka: {
    color: 'gold',
    label: 'Kafka · librdkafka',
    boundary: '禁止 AdminClient、自动提交和无界消费',
    supportsSchema: true,
  },
  websocket: {
    color: 'cyan',
    label: 'WebSocket · 有界会话',
    boundary: '连接固定到同一 Runner，丢失后从 Connect 重试',
    supportsSchema: false,
  },
}

export default function EventProtocolWorkspace({
  projectId,
  mode,
  enabled,
}: {
  projectId: string
  mode: EventProtocolMode
  enabled: boolean
}) {
  const state = useEventWorkspace(projectId, mode)
  const presentation = EVENT_PRESENTATION[mode]

  return (
    <>
      <EventFeatureAlert enabled={enabled} />
      <EventToolbar
        presentation={presentation}
        canImportSchema={presentation.supportsSchema && Boolean(state.selected)}
        onImportSchema={() => state.setSchemaOpen(true)}
        onCreateSource={() => state.setSourceOpen(true)}
      />
      <div className="protocol-workspace-grid event-protocol-grid">
        <EventSourceInventory
          items={pageItems(state.sources.data)}
          loading={state.sources.isLoading}
          selectedId={state.selected?.id ?? null}
          onSelect={(source) => state.setSelection(source.id)}
        />
        <EventConsole
          projectId={projectId}
          mode={mode}
          source={state.selected}
          schemas={pageItems(state.schemas.data)}
          enabled={enabled}
        />
        <EventSourceInspector source={state.selected} schemas={pageItems(state.schemas.data)} />
      </div>
      <EventSourceDialog
        open={state.sourceOpen}
        projectId={projectId}
        mode={mode}
        onClose={() => state.setSourceOpen(false)}
      />
      <EventSchemaDialog
        open={state.schemaOpen}
        projectId={projectId}
        source={state.selected}
        onClose={() => state.setSchemaOpen(false)}
      />
    </>
  )
}

function useEventWorkspace(projectId: string, mode: EventProtocolMode) {
  const [selection, setSelection] = useState<string | null>(null)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [schemaOpen, setSchemaOpen] = useState(false)
  const sources = useQuery({
    queryKey: ['event-sources', projectId, mode],
    queryFn: () => listEventSources(projectId, mode),
  })
  const selected = useMemo(
    () =>
      sources.data?.items.find((item) => item.id === selection) ?? sources.data?.items[0] ?? null,
    [selection, sources.data?.items],
  )
  const schemas = useQuery({
    queryKey: ['event-schemas', projectId, selected?.id],
    queryFn: () => listEventSchemas(projectId, requiredSource(selected).id),
    enabled: mode === 'kafka' && Boolean(selected),
  })

  return {
    selection,
    setSelection,
    sourceOpen,
    setSourceOpen,
    schemaOpen,
    setSchemaOpen,
    sources,
    selected,
    schemas,
  }
}

function EventFeatureAlert({ enabled }: { enabled: boolean }) {
  if (enabled) return null
  return (
    <Alert
      showIcon
      type="info"
      className="page-alert"
      title="事件协议能力当前关闭"
      description="事件源与 Schema 可继续管理；启用 Feature Flag 后才能 Produce、Consume 或 Exchange。"
    />
  )
}

function EventToolbar({
  presentation,
  canImportSchema,
  onImportSchema,
  onCreateSource,
}: {
  presentation: (typeof EVENT_PRESENTATION)[EventProtocolMode]
  canImportSchema: boolean
  onImportSchema: () => void
  onCreateSource: () => void
}) {
  return (
    <div className="event-protocol-toolbar">
      <Space>
        <Tag color={presentation.color}>{presentation.label}</Tag>
        <Typography.Text type="secondary">{presentation.boundary}</Typography.Text>
      </Space>
      <Space>
        {canImportSchema && (
          <Button icon={<ImportOutlined />} onClick={onImportSchema}>
            导入消息 Schema
          </Button>
        )}
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreateSource}>
          新建事件源
        </Button>
      </Space>
    </div>
  )
}

function EventSourceInventory({
  items,
  loading,
  selectedId,
  onSelect,
}: {
  items: EventSource[]
  loading: boolean
  selectedId: string | null
  onSelect: (source: EventSource) => void
}) {
  return (
    <div className="protocol-inventory">
      <Typography.Title level={4}>事件源版本</Typography.Title>
      <Table
        size="small"
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={{ pageSize: 8, hideOnSinglePage: true }}
        rowClassName={(item) => (item.id === selectedId ? 'selected-row' : '')}
        onRow={(item) => ({ onClick: () => onSelect(item) })}
        columns={[
          {
            title: '名称',
            render: (_, item) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text strong>{item.name}</Typography.Text>
                <Typography.Text type="secondary">v{item.version}</Typography.Text>
              </Space>
            ),
          },
          { title: '端点', render: (_, item) => item.endpoints[0] },
        ]}
      />
    </div>
  )
}

function EventConsole({
  projectId,
  mode,
  source,
  schemas,
  enabled,
}: {
  projectId: string
  mode: EventProtocolMode
  source: EventSource | null
  schemas: SchemaArtifact[]
  enabled: boolean
}) {
  if (!source)
    return (
      <div className="protocol-editor">
        <Empty description="选择或创建事件源开始调试" />
      </div>
    )
  return mode === 'kafka' ? (
    <KafkaConsole projectId={projectId} source={source} schemas={schemas} enabled={enabled} />
  ) : (
    <WebSocketConsole projectId={projectId} source={source} enabled={enabled} />
  )
}

function KafkaConsole({
  projectId,
  source,
  schemas,
  enabled,
}: {
  projectId: string
  source: EventSource
  schemas: SchemaArtifact[]
  enabled: boolean
}) {
  const [topic, setTopic] = useState('flowtest.orders')
  const [payload, setPayload] = useState('{"id":"order-42"}')
  const [schemaId, setSchemaId] = useState<string>()
  const [result, setResult] = useState<EventDebugResult | null>(null)
  const produce = useMutation({
    mutationFn: () =>
      produceKafkaMessage(source.id, {
        project_id: projectId,
        topic,
        value: parseJson(payload, '消息'),
        schema_id: schemaId,
        correlation_header: 'flowtest-correlation-id',
        correlation_id: 'order-42',
        timeout_seconds: 30,
      }),
    onSuccess: setResult,
    onError: (error) => void message.error(error.message),
  })
  const consume = useMutation({
    mutationFn: () =>
      consumeKafkaMessages(source.id, {
        project_id: projectId,
        topic,
        offset: 'earliest',
        maximum_messages: 10,
        schema_id: schemaId,
        correlation_header: 'flowtest-correlation-id',
        correlation_id: 'order-42',
        timeout_seconds: 30,
      }),
    onSuccess: setResult,
    onError: (error) => void message.error(error.message),
  })
  const request = (
    <Space orientation="vertical" className="protocol-form" size="middle">
      <Input
        aria-label="Kafka Topic"
        value={topic}
        onChange={(event) => setTopic(event.target.value)}
        prefix={<DatabaseOutlined />}
      />
      <Select
        aria-label="Kafka Schema"
        allowClear
        value={schemaId}
        options={schemas.map((schema) => ({
          value: schema.id,
          label: `${schema.name} · v${schema.version}`,
        }))}
        placeholder="JSON 或选择固定 Schema"
        onChange={setSchemaId}
      />
      <TextArea
        aria-label="Kafka Message"
        rows={10}
        value={payload}
        onChange={(event) => setPayload(event.target.value)}
      />
      <Space>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          disabled={!enabled}
          loading={produce.isPending}
          onClick={() => produce.mutate()}
        >
          Produce
        </Button>
        <Button
          icon={<PlayCircleOutlined />}
          disabled={!enabled}
          loading={consume.isPending}
          onClick={() => consume.mutate()}
        >
          Consume（最多 10 条）
        </Button>
      </Space>
    </Space>
  )
  return (
    <div className="protocol-editor">
      <Tabs
        items={[
          { key: 'request', label: '消息', children: request },
          { key: 'result', label: 'Exchange', children: <EventResult result={result} /> },
        ]}
      />
    </div>
  )
}

function WebSocketConsole({
  projectId,
  source,
  enabled,
}: {
  projectId: string
  source: EventSource
  enabled: boolean
}) {
  const [payloadKind, setPayloadKind] = useState<'json' | 'text'>('json')
  const [payload, setPayload] = useState('{"id":"order-42","action":"subscribe"}')
  const [correlation, setCorrelation] = useState('id')
  const [result, setResult] = useState<EventDebugResult | null>(null)
  const exchange = useMutation({
    mutationFn: () =>
      exchangeWebSocketMessage(source.id, {
        project_id: projectId,
        payload_kind: payloadKind,
        message: payloadKind === 'json' ? parseJson(payload, '消息') : payload,
        correlation_expression: correlation || undefined,
        correlation_value: correlation ? 'order-42' : undefined,
        maximum_messages: 10,
        timeout_seconds: 30,
      }),
    onSuccess: setResult,
    onError: (error) => void message.error(error.message),
  })
  return (
    <div className="protocol-editor">
      <Tabs
        items={[
          {
            key: 'request',
            label: '会话 Exchange',
            children: (
              <Space orientation="vertical" className="protocol-form" size="middle">
                <Input value={source.endpoints[0]} disabled prefix={<CloudServerOutlined />} />
                <Segmented
                  value={payloadKind}
                  options={[
                    { label: 'JSON', value: 'json' },
                    { label: 'Text', value: 'text' },
                  ]}
                  onChange={setPayloadKind}
                />
                <TextArea
                  aria-label="WebSocket Message"
                  rows={10}
                  value={payload}
                  onChange={(event) => setPayload(event.target.value)}
                />
                <Input
                  aria-label="Correlation Expression"
                  value={correlation}
                  onChange={(event) => setCorrelation(event.target.value)}
                  placeholder="JMESPath，例如 id"
                />
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  disabled={!enabled}
                  loading={exchange.isPending}
                  onClick={() => exchange.mutate()}
                >
                  Connect → Send → Await → Close
                </Button>
              </Space>
            ),
          },
          { key: 'result', label: 'Exchange', children: <EventResult result={result} /> },
        ]}
      />
    </div>
  )
}

function EventResult({ result }: { result: EventDebugResult | null }) {
  if (!result) return <Empty description="尚未执行" />
  return (
    <div>
      <Space>
        <Tag color="success">有界执行</Tag>
        <Tag>{result.duration_ms} ms</Tag>
      </Space>
      <pre className="protocol-result">{JSON.stringify(result.output, null, 2)}</pre>
    </div>
  )
}

function EventSourceInspector({
  source,
  schemas,
}: {
  source: EventSource | null
  schemas: SchemaArtifact[]
}) {
  return (
    <aside className="protocol-inspector">
      <Typography.Title level={4}>Context Inspector</Typography.Title>
      {!source ? (
        <Empty description="选择事件源查看固定信息" />
      ) : (
        <>
          <Typography.Text code>{source.config_sha256.slice(0, 16)}…</Typography.Text>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="协议">{source.kind}</Descriptions.Item>
            <Descriptions.Item label="版本">v{source.version}</Descriptions.Item>
            <Descriptions.Item label="端点">{source.endpoints.join(', ')}</Descriptions.Item>
            <Descriptions.Item label="消息 Schema">{schemas.length}</Descriptions.Item>
          </Descriptions>
          <Alert
            showIcon
            type="success"
            title="执行 Snapshot 固定"
            description="事件源、Schema 版本和 SHA-256 会随 Workflow Snapshot 保存。"
          />
        </>
      )}
    </aside>
  )
}

function EventSourceDialog({
  open,
  projectId,
  mode,
  onClose,
}: {
  open: boolean
  projectId: string
  mode: EventProtocolMode
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<{ name: string; endpoint: string; registry?: string }>()
  const mutation = useMutation({
    mutationFn: (values: { name: string; endpoint: string; registry?: string }) =>
      createEventSource({
        project_id: projectId,
        kind: mode,
        name: values.name,
        bootstrap_servers:
          mode === 'kafka'
            ? values.endpoint
                .split(',')
                .map((item) => item.trim())
                .filter(Boolean)
            : undefined,
        websocket_url: mode === 'websocket' ? values.endpoint.trim() : undefined,
        schema_registry_url: mode === 'kafka' && values.registry ? values.registry : undefined,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['event-sources', projectId, mode] })
      form.resetFields()
      onClose()
      void message.success('事件源已保存为不可变版本')
    },
    onError: (error) => void message.error(error.message),
  })
  return (
    <Modal
      title={`新建 ${mode === 'kafka' ? 'Kafka' : 'WebSocket'} 事件源`}
      open={open}
      confirmLoading={mutation.isPending}
      onCancel={onClose}
      onOk={() => form.validateFields().then((values) => mutation.mutate(values))}
      okText="保存事件源"
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item label="名称" name="name" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item
          label={mode === 'kafka' ? 'Bootstrap Servers' : 'WebSocket URL'}
          name="endpoint"
          rules={[{ required: true }]}
        >
          <Input
            placeholder={mode === 'kafka' ? 'broker-1:9092, broker-2:9092' : 'wss://host/ws'}
          />
        </Form.Item>
        {mode === 'kafka' && (
          <Form.Item label="Schema Registry（可选）" name="registry">
            <Input placeholder="https://registry.example.com" />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}

function EventSchemaDialog({
  open,
  projectId,
  source,
  onClose,
}: {
  open: boolean
  projectId: string
  source: EventSource | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<{
    mode: 'registry' | 'json_schema' | 'avro'
    name: string
    subject?: string
    content?: string
  }>()
  const importMode = Form.useWatch('mode', form)
  const mutation = useMutation({
    mutationFn: async (values: {
      mode: 'registry' | 'json_schema' | 'avro'
      name: string
      subject?: string
      content?: string
    }) => {
      const selected = requiredSource(source)
      if (values.mode === 'registry')
        return importEventRegistrySchema(projectId, selected.id, {
          name: values.name,
          subject: values.subject ?? '',
          version: 'latest',
          timeout_seconds: 30,
        })
      return createEventSchema(projectId, selected.id, {
        name: values.name,
        schema_format: values.mode,
        schema: values.content,
      })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['event-schemas', projectId, source?.id] })
      form.resetFields()
      onClose()
      void message.success('消息 Schema 已保存为不可变版本')
    },
    onError: (error) => void message.error(error.message),
  })
  return (
    <Modal
      title="导入 Kafka 消息 Schema"
      open={open}
      confirmLoading={mutation.isPending}
      onCancel={onClose}
      onOk={() => form.validateFields().then((values) => mutation.mutate(values))}
      okText="校验并保存"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={{ mode: 'registry' }}>
        <Form.Item label="来源" name="mode">
          <Select
            options={[
              { label: 'Schema Registry Subject', value: 'registry' },
              { label: 'JSON Schema 2020-12', value: 'json_schema' },
              { label: 'Avro Schema', value: 'avro' },
            ]}
          />
        </Form.Item>
        <Form.Item label="名称" name="name" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        {importMode === 'registry' ? (
          <Form.Item label="Subject" name="subject" rules={[{ required: true }]}>
            <Input placeholder="orders-value" />
          </Form.Item>
        ) : (
          <Form.Item label="Schema 内容" name="content" rules={[{ required: true }]}>
            <TextArea rows={12} />
          </Form.Item>
        )}
        <Form.Item label="执行超时上限">
          <InputNumber value={30} disabled addonAfter="秒" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function requiredSource(source: EventSource | null): EventSource {
  if (!source) throw new Error('请先选择事件源')
  return source
}

function parseJson(value: string, label: string): unknown {
  try {
    return JSON.parse(value)
  } catch {
    throw new Error(`${label} 必须是有效 JSON`)
  }
}

function pageItems<T>(page: { items: T[] } | undefined): T[] {
  return page?.items ?? []
}
