import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { workflowDefinition } from '../test/fixtures'
import { addControlBlock, appendRegionDelay } from './editor/control-blocks'
import WorkflowControlFields from './WorkflowControlFields'

it('adds a serial step through the control region panel', async () => {
  const definition = addControlBlock(workflowDefinition, 'foreach')
  const region = definition.regions![0]
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '添加等待步骤' }))
  expect(onRegionUpdate).toHaveBeenCalledOnce()
  expect(onRegionUpdate.mock.calls[0][0]).toEqual(
    expect.objectContaining({
      entry_node_id: region.entry_node_id,
      nodes: expect.arrayContaining([expect.objectContaining({ id: region.entry_node_id })]),
    }),
  )
  expect(onRegionUpdate.mock.calls[0][0].nodes).toHaveLength(2)
})

it('opens the region canvas with its persisted entry, exit, and node', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const region = appendRegionDelay(definition.regions![0])!
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const dialog = screen.getByRole('dialog', { name: 'body 区域画布' })
  expect(within(dialog).getByText('入口 · 等待 0 秒')).toBeInTheDocument()
  expect(within(dialog).getByText('等待 0 秒 · 出口')).toBeInTheDocument()
})

it('inserts a step after a selected region node from the canvas toolbar', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const region = definition.regions![0]
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const dialog = screen.getByRole('dialog', { name: 'body 区域画布' })
  const insert = within(dialog).getByRole('button', { name: '在后面插入等待' })
  expect(insert).toBeDisabled()
  fireEvent.click(within(dialog).getByTestId(`rf__node-${region.entry_node_id}`))
  expect(insert).toBeEnabled()
  await userEvent.click(insert)
  expect(onRegionUpdate).toHaveBeenCalledOnce()
  const next = onRegionUpdate.mock.calls[0][0]
  expect(next.nodes).toHaveLength(2)
  expect(next.edges).toEqual([
    expect.objectContaining({ source: region.entry_node_id, target: next.exit_node_ids[0] }),
  ])
})

it('inserts a versioned API from the canvas and excludes inactive APIs', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const region = definition.regions![0]
  const activeApi = {
    id: 'aa200000-0000-4000-8000-000000000001',
    project_id: 'project',
    folder_id: null,
    name: '活动接口',
    description: '',
    current_version: 4,
    is_active: true,
  }
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      apis={[activeApi, { ...activeApi, id: 'inactive', name: '停用接口', is_active: false }]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).queryByText('停用接口')).not.toBeInTheDocument()
  fireEvent.click(within(dialog).getByTestId(`rf__node-${region.entry_node_id}`))
  await userEvent.click(within(dialog).getByRole('button', { name: '在后面插入接口' }))
  expect(onRegionUpdate.mock.calls[0][0].nodes.at(-1)).toEqual(
    expect.objectContaining({
      type: 'api',
      config: expect.objectContaining({ api_definition_id: activeApi.id, api_version: 4 }),
    }),
  )
})

it('reports a mapped or conditional edge instead of inserting into it', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const region = appendRegionDelay(definition.regions![0])!
  region.edges[0].condition = 'true'
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const dialog = screen.getByRole('dialog', { name: 'body 区域画布' })
  fireEvent.click(within(dialog).getByTestId(`rf__node-${region.entry_node_id}`))
  await userEvent.click(within(dialog).getByRole('button', { name: '在后面插入等待' }))
  expect(within(dialog).getByRole('alert')).toHaveTextContent('无法安全插入')
  expect(onRegionUpdate).not.toHaveBeenCalled()
})

it('keeps the region canvas read-only when its workflow cannot be edited', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const region = definition.regions![0]
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      editable={false}
      onUpdate={vi.fn()}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const dialog = screen.getByRole('dialog', { name: 'body 区域画布' })
  fireEvent.click(within(dialog).getByTestId(`rf__node-${region.entry_node_id}`))
  expect(within(dialog).getByRole('button', { name: '在后面插入等待' })).toBeDisabled()
  expect(within(dialog).queryByRole('button', { name: '在后面插入接口' })).toBeNull()
})

it('adds an API step with a frozen API version to the inline region', async () => {
  const definition = addControlBlock(workflowDefinition, 'foreach')
  const region = definition.regions![0]
  const api = {
    id: 'aa200000-0000-4000-8000-000000000001',
    project_id: 'project',
    folder_id: null,
    name: '查询订单',
    description: '',
    current_version: 7,
    is_active: true,
  }
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      apis={[api]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '添加接口步骤' }))
  expect(onRegionUpdate).toHaveBeenCalledOnce()
  const updated = onRegionUpdate.mock.calls[0][0]
  expect(updated.nodes.at(-1)).toEqual(
    expect.objectContaining({
      type: 'api',
      config: expect.objectContaining({ api_definition_id: api.id, api_version: 7 }),
    }),
  )
  expect(updated.edges).toEqual([
    expect.objectContaining({ source: region.exit_node_ids[0], target: updated.exit_node_ids[0] }),
  ])
})

it('updates an inline API reference and version through the region panel', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const first = {
    id: 'aa200000-0000-4000-8000-000000000001',
    project_id: 'project',
    folder_id: null,
    name: '旧接口',
    description: '',
    current_version: 2,
    is_active: true,
  }
  const next = {
    ...first,
    id: 'aa200000-0000-4000-8000-000000000002',
    name: '新接口',
    current_version: 5,
  }
  const region = {
    ...definition.regions![0],
    nodes: [
      {
        ...definition.regions![0].nodes[0],
        type: 'api' as const,
        name: '接口请求',
        config: { api_definition_id: first.id, api_version: first.current_version },
      },
    ],
  }
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      apis={[first, next]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  await userEvent.click(screen.getByRole('combobox', { name: '接口请求 接口' }))
  await userEvent.click(screen.getByText('新接口'))
  expect(onRegionUpdate.mock.calls[0][0].nodes[0].config).toEqual({
    api_definition_id: next.id,
    api_version: 5,
  })
})

it('adds a break step through the serial loop panel', async () => {
  const definition = addControlBlock(workflowDefinition, 'repeat')
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[definition.regions![0]]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '添加退出循环' }))
  expect(onRegionUpdate.mock.calls[0][0].nodes.at(-1)).toEqual(
    expect.objectContaining({ capability_id: 'flow.control.break' }),
  )
})

it('keeps an unfinished region JSON draft while visual actions are disabled', async () => {
  const definition = addControlBlock(workflowDefinition, 'foreach')
  const region = definition.regions![0]
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  const editor = screen.getByRole('textbox', { name: 'body 区域定义' })
  await userEvent.type(editor, 'x')
  expect(screen.getByRole('button', { name: '添加等待步骤' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '添加退出循环' })).toBeDisabled()
  expect(onRegionUpdate).not.toHaveBeenCalled()
  expect(editor).toHaveValue(`${JSON.stringify(region, null, 2)}x`)
})

it('does not apply an old region JSON draft over a newer region revision', async () => {
  const definition = addControlBlock(workflowDefinition, 'foreach')
  const region = definition.regions![0]
  const onRegionUpdate = vi.fn()
  const node = definition.nodes.at(-1)!
  const view = render(
    <WorkflowControlFields
      node={node}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  const editor = screen.getByRole('textbox', { name: 'body 区域定义' })
  await userEvent.type(editor, 'x')
  view.rerender(
    <WorkflowControlFields
      node={node}
      regions={[{ ...region, outputs: { value: { kind: 'literal', value: 2 } } }]}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  expect(editor).toHaveValue(`${JSON.stringify(region, null, 2)}x`)
  await userEvent.click(screen.getByRole('button', { name: '应用区域' }))
  expect(onRegionUpdate).not.toHaveBeenCalled()
  expect(screen.getByText(/区域已从其他编辑更新/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: /丢\s*弃/ }))
  expect(editor).toHaveValue(
    JSON.stringify({ ...region, outputs: { value: { kind: 'literal', value: 2 } } }, null, 2),
  )
  expect(screen.getByRole('button', { name: '添加等待步骤' })).toBeEnabled()
})
