import CatalogPagination from '../../components/CatalogPagination'
import {
  CloudServerOutlined,
  DatabaseOutlined,
  ImportOutlined,
  PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
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
} from 'antd'
import { useState } from 'react'
import QueryFailureNotice from '../../components/QueryFailureNotice'
import { useProtocolLocation } from './protocol-location'
import { useProtocolImportFeedback } from './use-protocol-import-feedback'
import { useProtocolDebugResult } from './use-protocol-debug-result'
import { useProtocolRequestDraft } from './use-protocol-request-draft'
import type { KafkaRequestDraft, WebSocketRequestDraft } from './protocol-request-draft'
import { useProtocolCatalog, useSelectedProtocolAsset } from './use-protocol-catalog'

import {
  consumeKafkaMessages,
  createEventSchema,
  createEventSource,
  exchangeWebSocketMessage,
  importEventRegistrySchema,
  listEventSchemas,
  listEventSources,
  getEventSource,
  getEventSchema,
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
    label: 'Kafka · 消息调试',
    boundary: '手动发送与有界读取，不自动提交消费位点',
    supportsSchema: true,
  },
  websocket: {
    color: 'cyan',
    label: 'WebSocket · 有界会话',
    boundary: '单次会话最多接收10条消息，完成后关闭连接',
    supportsSchema: false,
  },
}

export default function EventProtocolWorkspace({
  projectId,
  mode,
  enabled,
  editable,
  executable,
}: {
  projectId: string
  mode: EventProtocolMode
  enabled: boolean
  editable: boolean
  executable: boolean
}) {
  const state = useEventWorkspace(projectId, mode)
  const presentation = EVENT_PRESENTATION[mode]

  return (
    <>
      <QueryFailureNotice queries={[state.selectionQuery, state.schemaSelection.query]} />
      <EventFeatureAlert enabled={enabled} />
      <div className="catalog-controls">
        <CatalogPagination query={state.sources} label="事件来源" />
        {mode === 'kafka' && <CatalogPagination query={state.schemas} label="项目消息 Schema" />}
      </div>
      <EventToolbar
        presentation={presentation}
        canImportSchema={editable && presentation.supportsSchema && Boolean(state.selected)}
        onImportSchema={state.openSchema}
        onCreateSource={editable ? () => state.setSourceOpen(true) : undefined}
      />
      <EventWorkspaceBody
        projectId={projectId}
        mode={mode}
        state={state}
        enabled={enabled && executable}
      />
      {state.sourceOpen && (
        <EventSourceDialog
          open
          editable={editable}
          projectId={projectId}
          mode={mode}
          onClose={() => state.setSourceOpen(false)}
        />
      )}
      {state.selected && state.schemaOpen === state.selected.id && (
        <EventSchemaDialog
          key={state.selected.id}
          open
          editable={editable}
          projectId={projectId}
          source={state.selected}
          onClose={() => state.setSchemaOpen(null)}
        />
      )}
    </>
  )
}

function EventWorkspaceBody({
  projectId,
  mode,
  state,
  enabled,
}: {
  projectId: string
  mode: EventProtocolMode
  state: ReturnType<typeof useEventWorkspace>
  enabled: boolean
}) {
  return (
    <div className="protocol-workspace-grid event-protocol-grid">
      <div>
        {state.selected && (
          <Typography.Paragraph>
            {state.selected.name} · v{state.selected.version}
          </Typography.Paragraph>
        )}
        <EventSourceInventory
          items={pageItems(state.sources.data)}
          loading={state.sources.isLoading}
          selectedId={state.selected?.id ?? null}
          onSelect={(source) => state.setSelection(source.id)}
        />
      </div>
      <EventConsole
        projectId={projectId}
        mode={mode}
        source={state.selected}
        schemas={pageItems(state.schemas.data)}
        enabled={enabled && (!state.schemaId || Boolean(state.schemaSelection.selected))}
        selectedSchema={state.schemaSelection.selected}
        onSelectSchema={state.selectSchema}
      />
      <EventSourceInspector source={state.selected} schemaTotal={state.schemas.data?.total} />
    </div>
  )
}

function useEventWorkspace(projectId: string, mode: EventProtocolMode) {
  const location = useProtocolLocation()
  const [sourceOpen, setSourceOpen] = useState(false)
  const [schemaOpen, setSchemaOpen] = useState<string | null>(null)
  const sources = useProtocolCatalog(
    'event-sources',
    projectId,
    mode,
    location.page,
    location.setPage,
    (page) => listEventSources(projectId, mode, page, 20),
    !location.error,
  )
  const selection = useSelectedProtocolAsset(
    projectId,
    `event-sources:${mode}`,
    location.id,
    pageItems(sources.data),
    (id) => getEventSource(projectId, id, mode),
    location.selectAsset,
    !location.error,
  )
  const selected = selection.selected
  const schemas = useProtocolCatalog(
    'event-schemas',
    projectId,
    selected?.id ?? '',
    location.schemaPage,
    location.setSchemaPage,
    (page) => listEventSchemas(projectId, requiredSource(selected).id, page, 20),
    mode === 'kafka' && Boolean(selected),
  )
  const schemaSelection = useSelectedProtocolAsset(
    projectId,
    `event-schemas:${selected?.id ?? ''}`,
    location.schemaId,
    pageItems(schemas.data),
    (id) => getEventSchema(projectId, requiredSource(selected).id, id),
    location.selectSchema,
    mode === 'kafka' && Boolean(selected) && !location.error,
    false,
  )

  return {
    schemaId: location.schemaId,
    selectSchema: location.selectSchema,
    schemaSelection,
    selectionQuery: selection.query,
    setSelection: location.selectAsset,
    sourceOpen,
    setSourceOpen,
    schemaOpen,
    setSchemaOpen,
    openSchema: () => setSchemaOpen(requiredSource(selected).id),
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
  onCreateSource?: () => void
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
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!onCreateSource}
          onClick={onCreateSource}
        >
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
        pagination={false}
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
  selectedSchema,
  onSelectSchema,
  enabled,
}: {
  projectId: string
  mode: EventProtocolMode
  source: EventSource | null
  schemas: SchemaArtifact[]
  selectedSchema: SchemaArtifact | null
  onSelectSchema: (id: string | null) => void
  enabled: boolean
}) {
  if (!source)
    return (
      <div className="protocol-editor">
        <Empty description="选择或创建事件源开始调试" />
      </div>
    )
  return mode === 'kafka' ? (
    <KafkaConsole
      key={`${projectId}:kafka:${source.id}:${source.version}:${source.config_sha256}:${selectedSchema?.id ?? 'json'}`}
      projectId={projectId}
      source={source}
      schemas={schemas}
      selectedSchema={selectedSchema}
      onSelectSchema={onSelectSchema}
      enabled={enabled}
    />
  ) : (
    <WebSocketConsole
      key={`${projectId}:websocket:${source.id}:${source.version}:${source.config_sha256}`}
      projectId={projectId}
      source={source}
      enabled={enabled}
    />
  )
}

function KafkaConsole({
  projectId,
  source,
  schemas,
  selectedSchema,
  onSelectSchema,
  enabled,
}: {
  projectId: string
  source: EventSource
  schemas: SchemaArtifact[]
  selectedSchema: SchemaArtifact | null
  onSelectSchema: (id: string | null) => void
  enabled: boolean
}) {
  const state = useProtocolDebugResult<EventDebugResult>()
  const { draft, patch, reset } = useProtocolRequestDraft<KafkaRequestDraft>(
    `${projectId}:kafka:${source.id}:${source.version}:${source.config_sha256}`,
    { mode: 'kafka', topic: 'flowtest.orders', payload: '{"id":"order-42"}' },
  )
  const { topic, payload } = draft
  const schemaOptions =
    selectedSchema && !schemas.some((item) => item.id === selectedSchema.id)
      ? [selectedSchema, ...schemas]
      : schemas
  function changeRequest(change: () => void) {
    state.invalidate()
    change()
  }
  const produce = useMutation({
    mutationFn: (input: KafkaRequestDraft & { schemaId?: string }) =>
      produceKafkaMessage(source.id, {
        project_id: projectId,
        topic: input.topic,
        value: parseJson(input.payload, '消息'),
        schema_id: input.schemaId,
        correlation_header: 'flowtest-correlation-id',
        correlation_id: 'order-42',
        timeout_seconds: 30,
      }),
    onMutate: state.begin,
    onSuccess: (value, _input, revision) => state.accept(value, revision),
    onError: (error, _input, revision) => state.fail(error, revision),
  })
  const consume = useMutation({
    mutationFn: (input: KafkaRequestDraft & { schemaId?: string }) =>
      consumeKafkaMessages(source.id, {
        project_id: projectId,
        topic: input.topic,
        offset: 'earliest',
        maximum_messages: 10,
        schema_id: input.schemaId,
        correlation_header: 'flowtest-correlation-id',
        correlation_id: 'order-42',
        timeout_seconds: 30,
      }),
    onMutate: state.begin,
    onSuccess: (value, _input, revision) => state.accept(value, revision),
    onError: (error, _input, revision) => state.fail(error, revision),
  })
  const request = (
    <Space orientation="vertical" className="protocol-form" size="middle">
      <Input
        aria-label="Kafka Topic"
        value={topic}
        onChange={(event) => changeRequest(() => patch({ topic: event.target.value }))}
        prefix={<DatabaseOutlined />}
      />
      <Select
        aria-label="Kafka Schema"
        allowClear
        value={selectedSchema?.id ?? null}
        options={schemaOptions.map((schema) => ({
          value: schema.id,
          label: `${schema.name} · v${schema.version}`,
        }))}
        placeholder="JSON 或选择固定 Schema"
        onChange={(value) => changeRequest(() => onSelectSchema(value ?? null))}
      />
      <TextArea
        aria-label="Kafka Message"
        rows={10}
        value={payload}
        onChange={(event) => changeRequest(() => patch({ payload: event.target.value }))}
      />
      <Button onClick={() => changeRequest(reset)}>重置Kafka请求草稿</Button>
      <Space>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          disabled={!enabled}
          loading={produce.isPending}
          onClick={() => produce.mutate({ ...draft, schemaId: selectedSchema?.id })}
        >
          Produce
        </Button>
        <Button
          icon={<PlayCircleOutlined />}
          disabled={!enabled}
          loading={consume.isPending}
          onClick={() => consume.mutate({ ...draft, schemaId: selectedSchema?.id })}
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
          {
            key: 'result',
            label: 'Exchange',
            children: <EventResult result={state.result} source={source} />,
          },
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
  const state = useProtocolDebugResult<EventDebugResult>()
  const { draft, patch, reset } = useProtocolRequestDraft<WebSocketRequestDraft>(
    `${projectId}:websocket:${source.id}:${source.version}:${source.config_sha256}`,
    {
      mode: 'websocket',
      payloadKind: 'json',
      payload: '{"id":"order-42","action":"subscribe"}',
      correlation: 'id',
    },
  )
  const { payloadKind, payload, correlation } = draft
  function changeRequest(change: () => void) {
    state.invalidate()
    change()
  }
  const exchange = useMutation({
    mutationFn: (input: WebSocketRequestDraft) =>
      exchangeWebSocketMessage(source.id, {
        project_id: projectId,
        payload_kind: input.payloadKind,
        message: input.payloadKind === 'json' ? parseJson(input.payload, '消息') : input.payload,
        correlation_expression: input.correlation || undefined,
        correlation_value: input.correlation ? 'order-42' : undefined,
        maximum_messages: 10,
        timeout_seconds: 30,
      }),
    onMutate: state.begin,
    onSuccess: (value, _input, revision) => state.accept(value, revision),
    onError: (error, _input, revision) => state.fail(error, revision),
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
                  onChange={(value: 'json' | 'text') =>
                    changeRequest(() => patch({ payloadKind: value }))
                  }
                />
                <TextArea
                  aria-label="WebSocket Message"
                  rows={10}
                  value={payload}
                  onChange={(event) => changeRequest(() => patch({ payload: event.target.value }))}
                />
                <Input
                  aria-label="Correlation Expression"
                  value={correlation}
                  onChange={(event) =>
                    changeRequest(() => patch({ correlation: event.target.value }))
                  }
                  placeholder="JMESPath，例如 id"
                />
                <Button onClick={() => changeRequest(reset)}>重置WebSocket请求草稿</Button>
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  disabled={!enabled}
                  loading={exchange.isPending}
                  onClick={() => exchange.mutate(draft)}
                >
                  Connect → Send → Await → Close
                </Button>
              </Space>
            ),
          },
          {
            key: 'result',
            label: 'Exchange',
            children: <EventResult result={state.result} source={source} />,
          },
        ]}
      />
    </div>
  )
}

function EventResult({ result, source }: { result: EventDebugResult | null; source: EventSource }) {
  if (!result) return <Empty description="尚未执行" />
  return (
    <div>
      <Space>
        <Tag color="blue">有界执行</Tag>
        <Tag>
          {source.name} · v{source.version}
        </Tag>
        <Tag>{result.duration_ms} ms</Tag>
      </Space>
      <Typography.Paragraph copyable>
        {source.id} · {source.config_sha256}
      </Typography.Paragraph>
      <pre className="protocol-result">{JSON.stringify(result.output, null, 2)}</pre>
    </div>
  )
}

function EventSourceInspector({
  source,
  schemaTotal,
}: {
  source: EventSource | null
  schemaTotal: number | undefined
}) {
  return (
    <aside className="protocol-inspector">
      <Typography.Title level={4}>事件源检查器</Typography.Title>
      {!source ? (
        <Empty description="选择事件源查看固定信息" />
      ) : (
        <>
          <Typography.Text code>{source.config_sha256.slice(0, 16)}…</Typography.Text>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="协议">{source.kind}</Descriptions.Item>
            <Descriptions.Item label="版本">v{source.version}</Descriptions.Item>
            <Descriptions.Item label="端点">{source.endpoints.join(', ')}</Descriptions.Item>
            <Descriptions.Item label="项目消息 Schema">
              {source.kind === 'kafka' ? (schemaTotal ?? '未提供') : '不适用'}
            </Descriptions.Item>
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
  editable,
}: {
  editable: boolean
  open: boolean
  projectId: string
  mode: EventProtocolMode
  onClose: () => void
}) {
  const feedback = useProtocolImportFeedback(editable)
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
      if (feedback.allowed()) {
        feedback.success('事件源已保存为不可变版本')
        onClose()
      }
    },
    onError: feedback.error,
  })
  return (
    <Modal
      title={`新建 ${mode === 'kafka' ? 'Kafka' : 'WebSocket'} 事件源`}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      okButtonProps={{ disabled: !editable || mutation.isPending, loading: mutation.isPending }}
      okText="保存事件源"
      destroyOnHidden
    >
      <Form
        form={form}
        disabled={!editable || mutation.isPending}
        onFinish={(values) => {
          if (feedback.allowed() && !mutation.isPending) mutation.mutate(values)
        }}
        layout="vertical"
      >
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
  editable,
}: {
  editable: boolean
  open: boolean
  projectId: string
  source: EventSource | null
  onClose: () => void
}) {
  const feedback = useProtocolImportFeedback(editable)
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
      if (feedback.allowed()) {
        feedback.success('消息 Schema 已保存为不可变版本')
        onClose()
      }
    },
    onError: feedback.error,
  })
  return (
    <Modal
      title="导入 Kafka 消息 Schema"
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      okButtonProps={{ disabled: !editable || mutation.isPending, loading: mutation.isPending }}
      okText="校验并保存"
      destroyOnHidden
    >
      <Form
        form={form}
        disabled={!editable || mutation.isPending}
        onFinish={(values) => {
          if (feedback.allowed() && !mutation.isPending) mutation.mutate(values)
        }}
        layout="vertical"
        initialValues={{ mode: 'registry' }}
      >
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
