import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import WorkflowDesigner from './WorkflowDesigner'
import { addTypedNode, connectNodes } from './workflow-graph'
import { apiDefinition, workflowDefinition } from '../test/fixtures'
import type { Artifact, WorkflowDefinition } from '../lib/api'

describe('WorkflowDesigner', () => {
  it('locks the published execution snapshot while a run is active', () => {
    render(
      <WorkflowDesigner
        definition={workflowDefinition}
        apis={[apiDefinition]}
        artifacts={[]}
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

function DesignerHarness({ initial }: { initial: WorkflowDefinition }) {
  const [definition, setDefinition] = useState(initial)
  return (
    <WorkflowDesigner
      definition={definition}
      apis={[apiDefinition]}
      artifacts={[datasetArtifact]}
      statuses={{}}
      editable
      onChange={setDefinition}
    />
  )
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
