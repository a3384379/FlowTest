import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import WorkflowDesigner from './WorkflowDesigner'
import {
  addEventProtocolNode,
  addProtocolNode,
  addTypedNode,
  autoLayoutWorkflow,
  connectNodes,
  pasteNode,
} from './workflow-graph'
import { apiDefinition, workflow, workflowDefinition } from '../test/fixtures'
import type { Artifact, Credential, WorkflowDefinition } from '../lib/api'
import type { EventSource, SchemaArtifact } from '../features/protocols/protocol-service'

describe('WorkflowDesigner', () => {
  it('locks the published execution snapshot while a run is active', () => {
    render(
      <WorkflowDesigner
        definition={workflowDefinition}
        apis={[apiDefinition]}
        artifacts={[]}
        credentials={[]}
        statuses={{ api: 'running' }}
        editable={false}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: /添加接口节点/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /添加结束节点/ })).toBeDisabled()
    fireEvent.click(screen.getByText('查询用户'))
    expect(screen.getByDisplayValue('查询用户')).toBeDisabled()
    expect(screen.getByRole('button', { name: /删除节点/ })).toBeDisabled()
    expect(screen.getByText('运行中')).toBeVisible()
  })

  it('shows an empty state before a workflow is selected', () => {
    render(
      <WorkflowDesigner
        definition={{
          schema_version: '1.0',
          variables: {},
          nodes: [],
          edges: [],
          settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
        }}
        apis={[]}
        artifacts={[]}
        credentials={[]}
        statuses={{}}
        editable
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText('请选择工作流')).toBeVisible()
  })

  it('configures S7 control nodes, datasets, and field mappings', async () => {
    const browser = userEvent.setup()
    render(<DesignerHarness initial={controlDefinition} />)

    fireEvent.click(screen.getByText('请求用户'))
    expect(screen.getByLabelText('映射源表达式')).toHaveValue('row.email')
    fireEvent.change(screen.getByLabelText('映射源表达式'), {
      target: { value: 'row.user.email' },
    })
    await browser.click(screen.getByRole('button', { name: /添加$/ }))
    expect(screen.getAllByLabelText('映射源表达式')).toHaveLength(2)
    await browser.click(screen.getAllByRole('button', { name: '删除映射' })[1])

    fireEvent.click(screen.getByText('提取邮箱'))
    expect(screen.getByDisplayValue('selected_email')).toBeVisible()
    fireEvent.change(screen.getByDisplayValue('selected_email'), {
      target: { value: 'mapped_email' },
    })

    fireEvent.click(screen.getByText('校验状态'))
    expect(screen.getByDisplayValue('status_code')).toBeVisible()
    expect(screen.getByDisplayValue('200')).toBeVisible()

    fireEvent.click(screen.getByText('判断启用'))
    expect(screen.getByDisplayValue('body.enabled')).toBeVisible()
    expect(screen.getByDisplayValue('true')).toBeVisible()

    fireEvent.click(screen.getByText('稍候'))
    expect(screen.getByDisplayValue('0.5')).toBeVisible()

    fireEvent.click(screen.getByText('用户数据'))
    expect(screen.getByText(/users\.json/)).toBeVisible()
    expect(screen.getByRole('button', { name: /数据集/ })).toBeDisabled()
  })

  it('adds each S7 node with maintainable defaults', () => {
    const delay = addTypedNode(workflowDefinition, 'delay', null)
    expect(delay.nodes.at(-1)?.config).toEqual({ seconds: 1 })
    const extracted = addTypedNode(workflowDefinition, 'extract', null)
    expect(extracted.nodes.at(-1)?.config).toMatchObject({
      source_node_id: 'end',
      expression: 'body',
    })
    const asserted = addTypedNode(workflowDefinition, 'assert', null)
    expect(asserted.nodes.at(-1)?.config.expected).toBe(200)
    const conditioned = addTypedNode(workflowDefinition, 'condition', null)
    expect(conditioned.nodes.at(-1)?.config.expected).toBe(true)
    const dataset = addTypedNode(workflowDefinition, 'dataset', datasetArtifact.id)
    expect(dataset.nodes.at(-1)?.config.artifact_id).toBe(datasetArtifact.id)
    expect(addTypedNode(workflowDefinition, 'end', null).nodes.at(-1)?.type).toBe('end')
  })

  it('adds bounded Kafka and WebSocket capabilities with pinned event sources', async () => {
    const produced = addEventProtocolNode(workflowDefinition, 'kafka.produce', kafkaSource)
    expect(produced.nodes.at(-1)).toMatchObject({
      capability_id: 'kafka.produce',
      capability_version: '3.0.0',
      configuration: { source_id: kafkaSource.id, topic: 'flowtest.orders' },
    })
    const consumed = addEventProtocolNode(workflowDefinition, 'kafka.consume', kafkaSource)
    expect(consumed.nodes.at(-1)?.configuration).toMatchObject({
      maximum_messages: 10,
      timeout_seconds: 30,
    })
    const exchanged = addEventProtocolNode(
      workflowDefinition,
      'websocket.exchange',
      websocketSource,
    )
    expect(exchanged.nodes.at(-1)?.configuration).toMatchObject({
      source_id: websocketSource.id,
      maximum_messages: 10,
    })

    const browser = userEvent.setup()
    render(
      <DesignerHarness
        initial={workflowDefinition}
        eventSources={[kafkaSource, websocketSource]}
      />,
    )
    await browser.click(screen.getByRole('button', { name: /Kafka Produce/ }))
    fireEvent.click(screen.getByText('Kafka Produce', { selector: '.flow-node strong' }))
    expect(screen.getByDisplayValue('flowtest.orders')).toBeVisible()
    expect(screen.getAllByText('订单 Kafka · v1').length).toBeGreaterThanOrEqual(2)
  })

  it('adds version-pinned SubFlow and bounded ForEach nodes', () => {
    const reference = { workflowId: workflow.id, workflowVersion: 3 }
    const subflow = addTypedNode(workflowDefinition, 'subflow', null, reference)
    expect(subflow.nodes.at(-1)?.config).toEqual({
      workflow_id: workflow.id,
      workflow_version: 3,
    })
    const loop = addTypedNode(workflowDefinition, 'for_each', null, reference)
    expect(loop.nodes.at(-1)?.config).toMatchObject({
      workflow_id: workflow.id,
      workflow_version: 3,
      source_node_id: 'end',
      expression: 'body.items',
      concurrency: 5,
      fail_fast: true,
    })
  })

  it('adds version-pinned GraphQL and gRPC capability nodes with isolated bindings', () => {
    const graphql = addProtocolNode(workflowDefinition, 'graphql', graphqlSchema)
    const grpc = addProtocolNode(graphql, 'grpc', grpcDescriptor)
    const graphqlNode = graphql.nodes.at(-1)
    const grpcNode = grpc.nodes.at(-1)

    expect(graphqlNode).toMatchObject({
      type: 'capability',
      capability_id: 'graphql.request',
      capability_version: '3.0.0',
      configuration: { schema_id: graphqlSchema.id },
    })
    expect(grpcNode).toMatchObject({
      capability_id: 'grpc.call',
      configuration: {
        descriptor_id: grpcDescriptor.id,
        service: 'flowtest.user.v1.UserService',
        method: 'GetUser',
      },
    })
    const copied = pasteNode(grpc, {
      ...grpcNode!,
      bindings: [{ input: 'request.id', expression: 'node_outputs.api.body.id' }],
    })
    expect(copied.nodes.at(-1)?.bindings).toEqual([
      { input: 'request.id', expression: 'node_outputs.api.body.id' },
    ])
    expect(copied.nodes.at(-1)?.bindings).not.toBe(grpcNode?.bindings)
  })

  it('edits protocol capability configuration, mTLS, and upstream bindings', async () => {
    const browser = userEvent.setup()
    const graphqlDefinition = protocolGraph('graphql')
    const graphqlView = render(
      <DesignerHarness
        initial={graphqlDefinition}
        graphqlSchemas={[graphqlSchema]}
        grpcDescriptors={[grpcDescriptor]}
      />,
    )

    fireEvent.click(screen.getByTestId('rf__node-graphql-4'))
    expect(screen.getByDisplayValue('https://api.example.com/graphql')).toBeVisible()
    await browser.clear(screen.getByLabelText('GraphQL Endpoint'))
    await browser.type(screen.getByLabelText('GraphQL Endpoint'), 'https://graphql.example.com')
    fireEvent.blur(screen.getByLabelText('Variables（JSON）'), {
      target: { value: '{"id":"initial"}' },
    })
    await browser.click(screen.getByRole('button', { name: 'plus 添加' }))
    expect(screen.getByLabelText('Capability 绑定源')).toHaveValue('node_outputs.api.body')
    await browser.type(screen.getByLabelText('Capability 绑定源'), '.id')
    await browser.clear(screen.getByLabelText('Capability 绑定目标'))
    await browser.type(screen.getByLabelText('Capability 绑定目标'), 'variables.id')
    graphqlView.unmount()

    render(
      <DesignerHarness
        initial={protocolGraph('grpc')}
        credentials={[grpcCredential]}
        graphqlSchemas={[graphqlSchema]}
        grpcDescriptors={[grpcDescriptor]}
      />,
    )
    fireEvent.click(screen.getByTestId('rf__node-grpc-4'))
    expect(screen.getByText(/flowtest\.user\.v1\.UserService/)).toBeVisible()
    const transportField = screen.getByText('传输安全').closest('label')
    if (!transportField) throw new Error('Transport security field was not rendered')
    await browser.click(within(transportField).getByRole('combobox'))
    await browser.click(screen.getByText('mTLS', { exact: true }))
    await browser.click(screen.getByLabelText('mTLS Credential'))
    await browser.click(screen.getByText(grpcCredential.name))
    fireEvent.blur(screen.getByLabelText('Request（JSON）'), {
      target: { value: '{"id":"42"}' },
    })
    fireEvent.blur(screen.getByLabelText('Metadata（JSON）'), {
      target: { value: '{"x-trace":"trace"}' },
    })
    await browser.click(screen.getByRole('button', { name: 'plus 添加' }))
    await browser.click(screen.getByRole('button', { name: '删除 Capability 绑定' }))
    expect(screen.queryByLabelText('Capability 绑定源')).not.toBeInTheDocument()
  })

  it('adds and configures credential-bound SQL and Redis nodes', () => {
    render(<DesignerHarness initial={workflowDefinition} credentials={dataCredentials} />)

    expect(screen.getByRole('button', { name: /只读 SQL/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Redis 读取/ })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: /只读 SQL/ }))
    fireEvent.click(screen.getByTestId('rf__node-sql-4'))
    expect(screen.getByDisplayValue('SELECT 1 AS healthy')).toBeVisible()
    fireEvent.change(screen.getByDisplayValue('SELECT 1 AS healthy'), {
      target: { value: 'SELECT id FROM users WHERE id = :id' },
    })
    expect(screen.getByDisplayValue('SELECT id FROM users WHERE id = :id')).toBeVisible()

    fireEvent.click(screen.getByRole('button', { name: /Redis 读取/ }))
    fireEvent.click(screen.getByTestId('rf__node-redis-5'))
    expect(screen.getByText(/Redis 仅允许 GET\/MGET/)).toBeVisible()

    const sql = addTypedNode(workflowDefinition, 'sql', null, null, dataCredentials)
    expect(sql.nodes.at(-1)?.config).toMatchObject({
      credential_id: dataCredentials[0].id,
      query: 'SELECT 1 AS healthy',
      timeout_seconds: 30,
    })
    const redis = addTypedNode(workflowDefinition, 'redis', null, null, dataCredentials)
    expect(redis.nodes.at(-1)?.config).toMatchObject({
      credential_id: dataCredentials[1].id,
      command: 'GET',
      arguments: ['key'],
    })
  })

  it('copies, pastes, automatically lays out, undoes, and redoes canvas changes', async () => {
    const browser = userEvent.setup()
    render(<DesignerHarness initial={workflowDefinition} />)

    fireEvent.click(screen.getByTestId('rf__node-api'))
    await browser.click(screen.getByRole('button', { name: /复制/ }))
    await browser.click(screen.getByRole('button', { name: /粘贴/ }))
    expect(screen.getByText('查询用户 副本')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /撤销/ }))
    expect(screen.queryByText('查询用户 副本')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: /重做/ }))
    expect(screen.getByText('查询用户 副本')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: /自动布局/ }))

    const pasted = pasteNode(workflowDefinition, workflowDefinition.nodes[1])
    expect(pasted.nodes.at(-1)?.name).toBe('查询用户 副本')
    expect(autoLayoutWorkflow(workflowDefinition).nodes.map((node) => node.position.x)).toEqual([
      0, 240, 480,
    ])
  })

  it('adds and configures published SubFlow and ForEach nodes', async () => {
    const browser = userEvent.setup()
    render(<DesignerHarness initial={advancedDefinition} />)

    fireEvent.click(screen.getByTestId('rf__node-foreach'))
    expect(screen.getByLabelText('固定版本')).toHaveValue('1')
    expect(screen.getByLabelText('JMESPath 表达式')).toHaveValue('body.items')
    expect(screen.getByLabelText('元素变量')).toHaveValue('item')
    expect(screen.getByLabelText('索引变量')).toHaveValue('index')

    await browser.clear(screen.getByLabelText('JMESPath 表达式'))
    await browser.type(screen.getByLabelText('JMESPath 表达式'), 'body.users')
    await browser.clear(screen.getByLabelText('元素变量'))
    await browser.type(screen.getByLabelText('元素变量'), 'user')
    await browser.clear(screen.getByLabelText('索引变量'))
    await browser.type(screen.getByLabelText('索引变量'), 'position')
    fireEvent.change(screen.getByLabelText('循环并发'), { target: { value: '8' } })
    await browser.click(screen.getByText('首项失败即停止'))
    await browser.click(screen.getByText('继续处理其他项'))

    await browser.click(screen.getByRole('button', { name: /子流程/ }))
    await browser.click(screen.getByRole('button', { name: /ForEach/ }))
    expect(screen.getAllByText('子流程').length).toBeGreaterThan(1)
    expect(screen.getByText('循环子流程')).toBeVisible()
  })

  it('labels the first two condition edges and rejects a third branch', () => {
    const base: WorkflowDefinition = {
      ...workflowDefinition,
      nodes: [
        ...workflowDefinition.nodes,
        {
          id: 'condition',
          type: 'condition',
          name: '条件',
          position: { x: 300, y: 0 },
          config: {},
        },
        { id: 'other', type: 'end', name: '另一结束', position: { x: 500, y: 0 }, config: {} },
      ],
      edges: [],
    }
    const trueBranch = connectNodes(base, [], connection('condition', 'api'))
    expect(trueBranch.edges[0].condition).toBe('true')
    const falseBranch = connectNodes(trueBranch, trueBranch.edges, connection('condition', 'end'))
    expect(falseBranch.edges[1].condition).toBe('false')
    const rejected = connectNodes(falseBranch, falseBranch.edges, connection('condition', 'other'))
    expect(rejected).toBe(falseBranch)
    expect(connectNodes(base, [], connection('api', 'api'))).toBe(base)
  })
})

function DesignerHarness({
  initial,
  credentials = [],
  graphqlSchemas = [],
  grpcDescriptors = [],
  eventSources = [],
}: {
  initial: WorkflowDefinition
  credentials?: Credential[]
  graphqlSchemas?: SchemaArtifact[]
  grpcDescriptors?: SchemaArtifact[]
  eventSources?: EventSource[]
}) {
  const [definition, setDefinition] = useState(initial)
  return (
    <WorkflowDesigner
      definition={definition}
      apis={[apiDefinition]}
      artifacts={[datasetArtifact]}
      workflows={[workflow]}
      credentials={credentials}
      graphqlSchemas={graphqlSchemas}
      grpcDescriptors={grpcDescriptors}
      eventSources={eventSources}
      statuses={{}}
      editable
      onChange={setDefinition}
    />
  )
}

const graphqlSchema: SchemaArtifact = {
  id: '00000000-0000-4000-8000-000000000801',
  project_id: apiDefinition.project_id,
  protocol: 'graphql',
  name: '用户 GraphQL',
  description: '',
  version: 1,
  source_format: 'graphql_sdl',
  content_sha256: 'a'.repeat(64),
  summary: { type_count: 3 },
  created_by_id: '00000000-0000-4000-8000-000000000001',
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

const grpcDescriptor: SchemaArtifact = {
  ...graphqlSchema,
  id: '00000000-0000-4000-8000-000000000802',
  protocol: 'grpc',
  name: '用户 gRPC',
  source_format: 'proto_source',
  content_sha256: 'b'.repeat(64),
  summary: {
    service_count: 1,
    services: [
      {
        name: 'flowtest.user.v1.UserService',
        methods: [{ name: 'GetUser', call_type: 'unary' }],
      },
    ],
  },
}

const kafkaSource: EventSource = {
  id: '00000000-0000-4000-8000-000000000805',
  project_id: apiDefinition.project_id,
  kind: 'kafka',
  name: '订单 Kafka',
  description: '',
  version: 1,
  endpoints: ['redpanda:9092'],
  schema_registry_url: 'http://redpanda:8081',
  config_sha256: 'c'.repeat(64),
  created_by_id: '00000000-0000-4000-8000-000000000001',
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

const websocketSource: EventSource = {
  ...kafkaSource,
  id: '00000000-0000-4000-8000-000000000806',
  kind: 'websocket',
  name: '订单 WebSocket',
  endpoints: ['ws://mock-target:8080/ws/echo'],
  schema_registry_url: null,
}

const grpcCredential: Credential = {
  id: '00000000-0000-4000-8000-000000000803',
  project_id: apiDefinition.project_id,
  name: '用户服务 mTLS',
  kind: 'grpc_mtls',
  host: 'grpc.example.com',
  port: 443,
  database_name: '',
  username: '',
  secret_provider: 'local',
  tls_enabled: true,
  created_by_id: '00000000-0000-4000-8000-000000000001',
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

function protocolGraph(protocol: 'graphql' | 'grpc'): WorkflowDefinition {
  const definition = addProtocolNode(
    workflowDefinition,
    protocol,
    protocol === 'graphql' ? graphqlSchema : grpcDescriptor,
  )
  const node = definition.nodes.at(-1)
  if (!node) throw new Error('Protocol node was not created')
  return {
    ...definition,
    edges: [
      definition.edges[0],
      { id: 'api-protocol', source: 'api', target: node.id, condition: null, mappings: [] },
      { id: 'protocol-end', source: node.id, target: 'end', condition: null, mappings: [] },
    ],
  }
}

function connection(source: string, target: string) {
  return { source, target, sourceHandle: null, targetHandle: null }
}

const datasetArtifact: Artifact = {
  id: '00000000-0000-4000-8000-000000000080',
  project_id: apiDefinition.project_id,
  filename: 'users.json',
  content_type: 'application/json',
  size_bytes: 2048,
  sha256: 'b'.repeat(64),
  purpose: 'upload',
  created_at: '2026-08-09T08:00:00Z',
}

const dataCredentials: Credential[] = [
  {
    id: '00000000-0000-4000-8000-000000000091',
    project_id: apiDefinition.project_id,
    name: '业务只读库',
    kind: 'postgresql',
    host: 'postgres',
    port: 5432,
    database_name: 'flowtest',
    username: 'reader',
    secret_provider: 'local',
    tls_enabled: false,
    created_by_id: '00000000-0000-4000-8000-000000000001',
    created_at: '2026-08-10T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z',
  },
  {
    id: '00000000-0000-4000-8000-000000000092',
    project_id: apiDefinition.project_id,
    name: '缓存只读',
    kind: 'redis',
    host: 'redis',
    port: 6379,
    database_name: '0',
    username: '',
    secret_provider: 'local',
    tls_enabled: false,
    created_by_id: '00000000-0000-4000-8000-000000000001',
    created_at: '2026-08-10T00:00:00Z',
    updated_at: '2026-08-10T00:00:00Z',
  },
]

const controlDefinition: WorkflowDefinition = {
  schema_version: '1.0',
  variables: {},
  nodes: [
    { id: 'start', type: 'start', name: '开始', position: { x: 0, y: 0 }, config: {} },
    {
      id: 'dataset',
      type: 'dataset',
      name: '用户数据',
      position: { x: 200, y: 0 },
      config: { artifact_id: datasetArtifact.id, format: 'json' },
    },
    {
      id: 'api',
      type: 'api',
      name: '请求用户',
      position: { x: 400, y: 0 },
      config: { api_definition_id: apiDefinition.id },
    },
    {
      id: 'extract',
      type: 'extract',
      name: '提取邮箱',
      position: { x: 600, y: 0 },
      config: { source_node_id: 'api', expression: 'body.email', variable: 'selected_email' },
    },
    {
      id: 'assert',
      type: 'assert',
      name: '校验状态',
      position: { x: 800, y: 0 },
      config: {
        source_node_id: 'api',
        expression: 'status_code',
        operator: 'equals',
        expected: 200,
      },
    },
    {
      id: 'condition',
      type: 'condition',
      name: '判断启用',
      position: { x: 1000, y: 0 },
      config: {
        source_node_id: 'api',
        expression: 'body.enabled',
        operator: 'equals',
        expected: true,
      },
    },
    {
      id: 'delay',
      type: 'delay',
      name: '稍候',
      position: { x: 1200, y: -80 },
      config: { seconds: 0.5 },
    },
    {
      id: 'other-delay',
      type: 'delay',
      name: '另一分支',
      position: { x: 1200, y: 80 },
      config: { seconds: 0 },
    },
    { id: 'end', type: 'end', name: '结束', position: { x: 1400, y: 0 }, config: {} },
  ],
  edges: [
    { id: 'start-data', source: 'start', target: 'dataset', condition: null, mappings: [] },
    {
      id: 'data-api',
      source: 'dataset',
      target: 'api',
      condition: null,
      mappings: [
        {
          source: { node_id: 'dataset', path: 'row.email' },
          transform: { kind: 'identity', template: '{{value}}' },
          target: { node_id: 'api', location: 'body', key: 'email' },
        },
      ],
    },
    { id: 'api-extract', source: 'api', target: 'extract', condition: null, mappings: [] },
    { id: 'extract-assert', source: 'extract', target: 'assert', condition: null, mappings: [] },
    {
      id: 'assert-condition',
      source: 'assert',
      target: 'condition',
      condition: null,
      mappings: [],
    },
    { id: 'true', source: 'condition', target: 'delay', condition: 'true', mappings: [] },
    {
      id: 'false',
      source: 'condition',
      target: 'other-delay',
      condition: 'false',
      mappings: [],
    },
    { id: 'delay-end', source: 'delay', target: 'end', condition: null, mappings: [] },
    {
      id: 'other-end',
      source: 'other-delay',
      target: 'end',
      condition: null,
      mappings: [],
    },
  ],
  settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
}

const advancedDefinition: WorkflowDefinition = {
  schema_version: '1.0',
  variables: {},
  nodes: [
    { id: 'start', type: 'start', name: '开始', position: { x: 0, y: 0 }, config: {} },
    {
      id: 'foreach',
      type: 'for_each',
      name: '批量用户',
      position: { x: 240, y: 0 },
      config: {
        workflow_id: workflow.id,
        workflow_version: 1,
        source_node_id: 'start',
        expression: 'body.items',
        item_variable: 'item',
        index_variable: 'index',
        concurrency: 5,
        fail_fast: true,
      },
    },
    { id: 'end', type: 'end', name: '结束', position: { x: 480, y: 0 }, config: {} },
  ],
  edges: [
    { id: 'start-loop', source: 'start', target: 'foreach', condition: null, mappings: [] },
    { id: 'loop-end', source: 'foreach', target: 'end', condition: null, mappings: [] },
  ],
  settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
}
