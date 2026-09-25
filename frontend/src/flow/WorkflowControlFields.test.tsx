import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import type { WorkflowRegion } from '../lib/api'
import { workflowDefinition } from '../test/fixtures'
import {
  addControlBlock,
  appendRegionDelay,
  insertNestedControlBlock,
  moveRegionStep,
  removeRegionStep,
} from './editor/control-blocks'
import { NodeEditContext, type NodeEditContextValue } from './editor/node-edit-session'
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

it('deletes a linear region step and reconnects its neighbors after confirmation', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const first = appendRegionDelay(definition.regions![0])!
  const region = appendRegionDelay(first)!
  const middleId = first.exit_node_ids[0]
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
  fireEvent.click(within(dialog).getByTestId(`rf__node-${middleId}`))
  await userEvent.click(within(dialog).getByRole('button', { name: '删除所选步骤' }))
  await userEvent.click(screen.getByRole('button', { name: 'OK' }))
  const updated = onRegionUpdate.mock.calls[0][0]
  expect(updated.nodes.map((node: { id: string }) => node.id)).toEqual([
    region.entry_node_id,
    region.exit_node_ids[0],
  ])
  expect(updated.edges).toEqual([
    expect.objectContaining({ source: region.entry_node_id, target: region.exit_node_ids[0] }),
  ])
})

it('moves a linear region step while preserving node and edge identities', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const first = appendRegionDelay(definition.regions![0])!
  const region = appendRegionDelay(first)!
  const ids = region.nodes.map((node) => node.id)
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
  fireEvent.click(within(dialog).getByTestId(`rf__node-${ids[1]}`))
  await userEvent.click(within(dialog).getByRole('button', { name: '向前移动' }))
  const moved = onRegionUpdate.mock.calls[0][0]
  expect(moved.nodes.map((node: { id: string }) => node.id)).toEqual([ids[1], ids[0], ids[2]])
  expect(moved.entry_node_id).toBe(ids[1])
  expect(moved.exit_node_ids).toEqual([ids[2]])
  expect(moved.edges.map((edge: { id: string }) => edge.id)).toEqual(
    region.edges.map((edge) => edge.id),
  )
  expect(
    moved.edges.map((edge: { source: string; target: string }) => [edge.source, edge.target]),
  ).toEqual([
    [ids[1], ids[0]],
    [ids[0], ids[2]],
  ])
})

it('inserts a nested control from the region canvas as one definition change', async () => {
  const definition = addControlBlock(workflowDefinition, 'group')
  const region = definition.regions![0]
  const onStructureChange = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      definition={definition}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onStructureChange={onStructureChange}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const dialog = screen.getByRole('dialog', { name: 'body 区域画布' })
  fireEvent.click(within(dialog).getByTestId(`rf__node-${region.entry_node_id}`))
  await userEvent.click(within(dialog).getByRole('button', { name: '在后面插入控制块' }))
  const next = onStructureChange.mock.calls[0][0]
  expect(next.nodes).toEqual(definition.nodes)
  expect(next.regions).toHaveLength(2)
  expect(next.regions[0].nodes.at(-1)?.capability_id).toBe('flow.control.group')
})

it('opens a nested control region from its parent canvas', async () => {
  const base = addControlBlock(workflowDefinition, 'group')
  const parent = base.regions![0]
  const definition = insertNestedControlBlock(base, parent.id, parent.entry_node_id!, 'if')!
  const region = definition.regions!.find((item) => item.id === parent.id)!
  const nested = region.nodes.at(-1)!
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      definition={definition}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onStructureChange={vi.fn()}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const parentCanvas = screen.getByRole('dialog', { name: 'body 区域画布' })
  fireEvent.click(within(parentCanvas).getByTestId(`rf__node-${nested.id}`))
  await userEvent.click(screen.getByRole('button', { name: '打开嵌套 true 区域' }))
  expect(screen.getByText('true 区域画布').closest('[role="dialog"]')).toBeInTheDocument()
})

it('edits a nested control configuration through the parent region canvas', async () => {
  const base = addControlBlock(workflowDefinition, 'group')
  const parent = base.regions![0]
  const definition = insertNestedControlBlock(base, parent.id, parent.entry_node_id!, 'repeat')!
  const region = definition.regions!.find((item) => item.id === parent.id)!
  const nested = region.nodes.at(-1)!
  const onRegionUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      definition={definition}
      regions={[region]}
      editable
      onUpdate={vi.fn()}
      onStructureChange={vi.fn()}
      onRegionUpdate={onRegionUpdate}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const canvas = screen.getByRole('dialog', { name: 'body 区域画布' })
  fireEvent.click(within(canvas).getByTestId(`rf__node-${nested.id}`))
  const count = within(canvas).getByRole('spinbutton', { name: '重复次数' })
  await userEvent.clear(count)
  await userEvent.type(count, '5')
  await userEvent.tab()
  const updated = onRegionUpdate.mock.lastCall?.[0] as WorkflowRegion
  expect(updated.nodes.find((item) => item.id === nested.id)?.configuration?.count).toBe(5)
})

it('keeps a nested condition value draft out of the outer node edit session', async () => {
  const base = addControlBlock(workflowDefinition, 'group')
  const parent = base.regions![0]
  const definition = insertNestedControlBlock(base, parent.id, parent.entry_node_id!, 'if')!
  const region = definition.regions!.find((item) => item.id === parent.id)!
  const nested = region.nodes.at(-1)!
  const onRegionUpdate = vi.fn()
  const outerSetRaw = vi.fn()
  const outerContext = {
    draft: { rawFields: {} },
    setRaw: outerSetRaw,
    clearRaw: vi.fn(),
  } as unknown as NodeEditContextValue
  render(
    <NodeEditContext.Provider value={outerContext}>
      <WorkflowControlFields
        node={definition.nodes.at(-1)!}
        definition={definition}
        regions={[region]}
        editable
        onUpdate={vi.fn()}
        onStructureChange={vi.fn()}
        onRegionUpdate={onRegionUpdate}
      />
    </NodeEditContext.Provider>,
  )
  await userEvent.click(screen.getByRole('button', { name: '打开区域画布' }))
  const canvas = screen.getByRole('dialog', { name: 'body 区域画布' })
  fireEvent.click(within(canvas).getByTestId(`rf__node-${nested.id}`))
  await userEvent.clear(within(canvas).getByRole('textbox', { name: '判断条件 右侧 JSON 值' }))
  await userEvent.type(
    within(canvas).getByRole('textbox', { name: '判断条件 右侧 JSON 值' }),
    'false',
  )
  await userEvent.click(within(canvas).getAllByRole('button', { name: '应用值' })[1])
  expect(outerSetRaw).not.toHaveBeenCalled()
  const updated = onRegionUpdate.mock.lastCall?.[0] as WorkflowRegion
  const condition = updated.nodes.find((item) => item.id === nested.id)?.configuration?.condition
  expect(condition).toEqual(expect.objectContaining({ right: { kind: 'literal', value: false } }))
})

it('refuses to move a region step across mapped edges or node dependencies', () => {
  const first = appendRegionDelay(addControlBlock(workflowDefinition, 'group').regions![0])!
  const region = appendRegionDelay(first)!
  const firstId = region.entry_node_id!
  expect(
    moveRegionStep(
      {
        ...region,
        edges: [{ ...region.edges[0], condition: 'true' }, ...region.edges.slice(1)],
      },
      firstId,
      1,
    ),
  ).toBeNull()
  expect(
    moveRegionStep(
      {
        ...region,
        nodes: region.nodes.map((node, index) =>
          index === 1 ? { ...node, config: { source: firstId } } : node,
        ),
      },
      firstId,
      1,
    ),
  ).toBeNull()
})

it('preserves a region step when its edge or output still references it', () => {
  const region = appendRegionDelay(addControlBlock(workflowDefinition, 'group').regions![0])!
  const firstId = region.entry_node_id!
  expect(
    removeRegionStep(
      {
        ...region,
        edges: [
          {
            ...region.edges[0],
            mappings: [
              {
                source: { node_id: firstId, path: 'value' },
                transform: { kind: 'identity', template: '' },
                target: { node_id: region.exit_node_ids[0], location: 'variable', key: 'value' },
              },
            ],
          },
        ],
      },
      firstId,
    ),
  ).toBeNull()
  expect(
    removeRegionStep(
      { ...region, outputs: { value: { kind: 'node_output', node_id: firstId, path: [] } } },
      firstId,
    ),
  ).toBeNull()
  expect(removeRegionStep(region, 'missing')).toBeNull()
  expect(
    removeRegionStep(
      {
        ...region,
        nodes: region.nodes.map((node) =>
          node.id === firstId ? node : { ...node, config: { source: `node_outputs.${firstId}` } },
        ),
      },
      firstId,
    ),
  ).toBeNull()
  expect(
    removeRegionStep(
      {
        ...region,
        nodes: region.nodes.map((node) =>
          node.id === firstId ? { ...node, capability_id: 'flow.control.group' } : node,
        ),
      },
      firstId,
    ),
  ).toBeNull()
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
  await userEvent.click(screen.getByRole('button', { name: /^丢\s*弃$/ }))
  expect(editor).toHaveValue(
    JSON.stringify({ ...region, outputs: { value: { kind: 'literal', value: 2 } } }, null, 2),
  )
  expect(screen.getByRole('button', { name: '添加等待步骤' })).toBeEnabled()
})

it('adds a declared condition-loop state with a bounded per-round update', async () => {
  const definition = addControlBlock(workflowDefinition, 'while')
  const node = definition.nodes.at(-1)!
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={node}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.type(screen.getByRole('textbox', { name: '新状态名' }), 'page')
  await userEvent.click(screen.getByRole('button', { name: '添加状态字段' }))
  const updated = onUpdate.mock.calls[0][0]
  expect(updated.configuration).toEqual({
    ...node.configuration,
    state: { page: { kind: 'literal', value: 0 } },
    update: { page: { kind: 'add', value: { kind: 'literal', value: 1 } } },
  })
})

it('edits one condition-loop state source without replacing the loop policy', async () => {
  const definition = addControlBlock(workflowDefinition, 'until')
  const node = definition.nodes.at(-1)!
  const configured = {
    ...node,
    configuration: {
      ...node.configuration,
      state: { page: { kind: 'literal', value: 1 } },
      update: { page: { kind: 'add', value: { kind: 'literal', value: 1 } } },
    },
  }
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={configured}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  fireEvent.change(screen.getByRole('textbox', { name: 'page 初始值 JSON 值' }), {
    target: { value: '2' },
  })
  await userEvent.click(
    within(screen.getByLabelText('page 初始值')).getByRole('button', { name: '应用值' }),
  )
  expect(onUpdate.mock.calls[0][0].configuration).toEqual({
    ...configured.configuration,
    state: { page: { kind: 'literal', value: 2 } },
  })
})

it('configures a condition-loop state from a scoped variable path', async () => {
  const definition = addControlBlock(workflowDefinition, 'do_while')
  const node = {
    ...definition.nodes.at(-1)!,
    configuration: {
      ...definition.nodes.at(-1)!.configuration,
      state: { cursor: { kind: 'literal', value: null } },
      update: {},
    },
  }
  const onUpdate = vi.fn()
  const props = {
    regions: definition.regions!,
    editable: true,
    onUpdate,
    onRegionUpdate: vi.fn(),
  }
  const view = render(<WorkflowControlFields node={node} {...props} />)
  await userEvent.click(screen.getByRole('combobox', { name: 'cursor 初始值 来源类型' }))
  await userEvent.click(screen.getByText('作用域变量'))
  const changed = onUpdate.mock.calls.at(-1)![0]
  expect(changed.configuration.state.cursor).toEqual({
    kind: 'variable',
    scope: 'state',
    path: ['page'],
  })
  view.rerender(<WorkflowControlFields node={changed} {...props} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'cursor 初始值 路径 第 1 段' }), {
    target: { value: 'nextCursor' },
  })
  expect(onUpdate.mock.calls.at(-1)![0].configuration.state.cursor.path).toEqual(['nextCursor'])
})

it('selects a declared runtime input from the source browser', async () => {
  const expanded = addControlBlock(workflowDefinition, 'while')
  const base = expanded.nodes.at(-1)!
  const node = {
    ...base,
    configuration: {
      ...base.configuration,
      state: { cursor: { kind: 'literal', value: null } },
      update: {},
    },
  }
  const definition = {
    ...expanded,
    runtime_inputs: [
      {
        name: 'caseId',
        value_type: 'string' as const,
        required: true,
        nullable: false,
        description: '',
      },
    ],
  }
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={node}
      definition={definition}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('combobox', { name: 'cursor 初始值 来源浏览器' }))
  await userEvent.click(screen.getByText('运行输入 · caseId'))
  expect(onUpdate.mock.calls.at(-1)![0].configuration.state.cursor).toEqual({
    kind: 'variable',
    scope: 'runtime',
    path: ['caseId'],
  })
})

it('binds the ForEach collection to a declared runtime input', async () => {
  const expanded = addControlBlock(workflowDefinition, 'foreach')
  const definition = {
    ...expanded,
    runtime_inputs: [
      {
        name: 'cases',
        value_type: 'array' as const,
        required: true,
        nullable: false,
        description: '',
      },
    ],
  }
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      definition={definition}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('combobox', { name: '遍历集合来源' }))
  await userEvent.click(screen.getByText('运行输入 · cases'))
  expect(onUpdate.mock.calls.at(-1)![0].configuration.collection).toEqual({
    kind: 'variable',
    scope: 'runtime',
    path: ['cases'],
  })
})

it('selects an IF operand without replacing the rest of its condition', async () => {
  const expanded = addControlBlock(workflowDefinition, 'if')
  const definition = {
    ...expanded,
    runtime_inputs: [
      {
        name: 'status',
        value_type: 'string' as const,
        required: true,
        nullable: false,
        description: '',
      },
    ],
  }
  const node = definition.nodes.at(-1)!
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={node}
      definition={definition}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('combobox', { name: '判断条件 左侧 来源浏览器' }))
  await userEvent.click(screen.getByText('运行输入 · status'))
  expect(onUpdate.mock.calls.at(-1)![0].configuration.condition).toEqual({
    ...(node.configuration!.condition as Record<string, unknown>),
    left: { kind: 'variable', scope: 'runtime', path: ['status'] },
  })
})

it('converts a Switch to rule conditions and edits one branch without changing its identity', async () => {
  const definition = addControlBlock(workflowDefinition, 'switch')
  const node = definition.nodes.at(-1)!
  const onUpdate = vi.fn()
  const props = {
    definition,
    regions: definition.regions!,
    editable: true,
    onUpdate,
    onRegionUpdate: vi.fn(),
  }
  const view = render(<WorkflowControlFields node={node} {...props} />)
  await userEvent.click(screen.getByRole('combobox', { name: '多分支模式' }))
  await userEvent.click(screen.getByText('按条件匹配'))
  const switched = onUpdate.mock.calls.at(-1)![0]
  expect(switched.configuration.branches[0]).toMatchObject({
    id: 'first',
    match: null,
    condition: { kind: 'compare', operator: 'equals' },
  })
  view.rerender(<WorkflowControlFields node={switched} {...props} />)
  await userEvent.click(screen.getByRole('combobox', { name: '分支 分支一 条件 运算符' }))
  await userEvent.click(screen.getAllByText('不等于').at(-1)!)
  const edited = onUpdate.mock.calls.at(-1)![0].configuration
  expect(edited.branches[0]).toMatchObject({
    id: 'first',
    body: (node.configuration!.branches as { body: unknown }[])[0].body,
    condition: { operator: 'not_equals' },
  })
  expect(edited.branches[1]).toEqual(switched.configuration.branches[1])
})

it('renames and reorders Switch branches without changing their IDs or region ownership', async () => {
  const definition = addControlBlock(workflowDefinition, 'switch')
  const node = definition.nodes.at(-1)!
  const onUpdate = vi.fn()
  const props = {
    definition,
    regions: definition.regions!,
    editable: true,
    onUpdate,
    onRegionUpdate: vi.fn(),
  }
  const view = render(<WorkflowControlFields node={node} {...props} />)
  const name = screen.getByRole('textbox', { name: '分支 first 名称' })
  await userEvent.clear(name)
  await userEvent.type(name, '优先分支')
  fireEvent.blur(name)
  const renamed = onUpdate.mock.calls.at(-1)![0]
  expect(renamed.configuration.branches[0]).toMatchObject({ id: 'first', label: '优先分支' })
  view.rerender(<WorkflowControlFields node={renamed} {...props} />)
  await userEvent.click(screen.getAllByRole('button', { name: '下移分支' })[0])
  const moved = onUpdate.mock.calls.at(-1)![0]
  expect(moved.configuration.branches.map((branch: { id: string }) => branch.id)).toEqual([
    'second',
    'first',
  ])
  expect(moved.configuration.branches[1]).toEqual(renamed.configuration.branches[0])
  expect(definition.regions?.map((region) => region.role)).toEqual([
    'case:first',
    'case:second',
    'default',
  ])
})

it('offers atomic Switch branch creation and default behavior changes', async () => {
  const definition = addControlBlock(workflowDefinition, 'switch')
  const onStructureChange = vi.fn()
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      definition={definition}
      regions={definition.regions!}
      editable
      onUpdate={vi.fn()}
      onStructureChange={onStructureChange}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '添加分支' }))
  expect(onStructureChange.mock.calls.at(-1)![0].regions).toHaveLength(4)
  await userEvent.click(screen.getByRole('combobox', { name: '默认分支行为' }))
  await userEvent.click(screen.getByText('无匹配时跳过'))
  expect(onStructureChange).toHaveBeenCalledTimes(1)
  await userEvent.click(screen.getByRole('button', { name: '确定切换' }))
  const skipped = onStructureChange.mock.calls.at(-1)![0]
  expect(skipped.nodes.at(-1)!.configuration.default).toEqual({ behavior: 'skip', body: null })
  expect(skipped.regions.map((region: { role: string }) => region.role)).toEqual([
    'case:first',
    'case:second',
  ])
})

it('edits ForEach execution limits while preserving other policy values', async () => {
  const definition = addControlBlock(workflowDefinition, 'foreach')
  const node = definition.nodes.at(-1)!
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={node}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  fireEvent.change(screen.getByRole('spinbutton', { name: '最大并发数' }), {
    target: { value: '3' },
  })
  expect(onUpdate.mock.calls.at(-1)![0].configuration.policy).toEqual({
    ...(node.configuration!.policy as Record<string, unknown>),
    concurrency: 3,
  })
  expect(screen.getByRole('spinbutton', { name: '最大迭代次数' })).toHaveValue('1000')
})

it('keeps condition loops serial while exposing their finite iteration limit', () => {
  const definition = addControlBlock(workflowDefinition, 'while')
  render(
    <WorkflowControlFields
      node={definition.nodes.at(-1)!}
      regions={definition.regions!}
      editable
      onUpdate={vi.fn()}
      onRegionUpdate={vi.fn()}
    />,
  )
  expect(screen.queryByRole('spinbutton', { name: '最大并发数' })).not.toBeInTheDocument()
  expect(screen.getByRole('spinbutton', { name: '最大迭代次数' })).toHaveValue('3')
  expect(screen.queryByRole('combobox', { name: '出错策略' })).not.toBeInTheDocument()
})

it('uses the parallel error policy choices without exposing loop iteration settings', async () => {
  const definition = addControlBlock(workflowDefinition, 'parallel')
  const node = definition.nodes.at(-1)!
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={node}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  expect(screen.queryByRole('spinbutton', { name: '最大迭代次数' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('combobox', { name: '出错策略' }))
  await userEvent.click(screen.getByText('收集所有分支结果'))
  expect(onUpdate.mock.calls.at(-1)![0].configuration.policy).toEqual({
    ...(node.configuration!.policy as Record<string, unknown>),
    on_error: 'collect_all',
  })
})

it('offers initialized loop state as a condition operand', async () => {
  const definition = addControlBlock(workflowDefinition, 'while')
  const base = definition.nodes.at(-1)!
  const node = {
    ...base,
    configuration: {
      ...base.configuration,
      state: { cursor: { kind: 'literal', value: 0 } },
      update: {},
    },
  }
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={node}
      definition={definition}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('combobox', { name: '循环条件 左侧 来源浏览器' }))
  await userEvent.click(screen.getByText('当前块状态 · cursor'))
  expect(onUpdate.mock.calls.at(-1)![0].configuration.condition.left).toEqual({
    kind: 'variable',
    scope: 'state',
    path: ['cursor'],
  })
})

it('protects an unfinished control configuration draft from a newer visual edit', async () => {
  const definition = addControlBlock(workflowDefinition, 'while')
  const node = definition.nodes.at(-1)!
  const onUpdate = vi.fn()
  const props = {
    regions: definition.regions!,
    editable: true,
    onUpdate,
    onRegionUpdate: vi.fn(),
  }
  const view = render(<WorkflowControlFields node={node} {...props} />)
  const editor = screen.getByRole('textbox', { name: '控制块配置 JSON' })
  fireEvent.change(editor, { target: { value: `${JSON.stringify(node.configuration, null, 2)}x` } })
  expect(screen.getByRole('button', { name: '添加状态字段' })).toBeDisabled()
  const newer = {
    ...node,
    configuration: { ...node.configuration, state: { page: { kind: 'literal', value: 1 } } },
  }
  view.rerender(<WorkflowControlFields node={newer} {...props} />)
  await userEvent.click(screen.getByRole('button', { name: '应用配置' }))
  expect(onUpdate).not.toHaveBeenCalled()
  expect(screen.getByText(/配置已从其他编辑更新/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: '丢弃配置草稿' }))
  expect(editor).toHaveValue(JSON.stringify(newer.configuration, null, 2))
  expect(screen.getByRole('button', { name: '添加状态字段' })).toBeEnabled()
})

it('rejects invalid control JSON and restores visual editing after discard', async () => {
  const definition = addControlBlock(workflowDefinition, 'repeat')
  const node = definition.nodes.at(-1)!
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={node}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  const editor = screen.getByRole('textbox', { name: '控制块配置 JSON' })
  fireEvent.change(editor, { target: { value: '[' } })
  expect(screen.getAllByRole('spinbutton')[0]).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: '应用配置' }))
  expect(screen.getByText('控制块配置必须是有效的 JSON 对象。')).toBeVisible()
  fireEvent.change(editor, { target: { value: '[]' } })
  await userEvent.click(screen.getByRole('button', { name: '应用配置' }))
  expect(screen.getByText('控制块配置必须是有效的 JSON 对象。')).toBeVisible()
  expect(onUpdate).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: '丢弃配置草稿' }))
  expect(editor).toHaveValue(JSON.stringify(node.configuration, null, 2))
  expect(screen.getAllByRole('spinbutton')[0]).toBeEnabled()
})

it('validates condition-loop state names and removes a state with its update', async () => {
  const definition = addControlBlock(workflowDefinition, 'while')
  const node = {
    ...definition.nodes.at(-1)!,
    configuration: {
      ...definition.nodes.at(-1)!.configuration,
      state: { page: { kind: 'literal', value: 0 } },
      update: { page: { kind: 'add', value: { kind: 'literal', value: 1 } } },
    },
  }
  const onUpdate = vi.fn()
  render(
    <WorkflowControlFields
      node={node}
      regions={definition.regions!}
      editable
      onUpdate={onUpdate}
      onRegionUpdate={vi.fn()}
    />,
  )
  const input = screen.getByRole('textbox', { name: '新状态名' })
  await userEvent.type(input, 'page')
  await userEvent.click(screen.getByRole('button', { name: '添加状态字段' }))
  expect(screen.getByText(/状态名须唯一/)).toBeVisible()
  await userEvent.clear(input)
  await userEvent.type(input, '1bad')
  await userEvent.click(screen.getByRole('button', { name: '添加状态字段' }))
  expect(onUpdate).not.toHaveBeenCalled()
  await userEvent.click(
    within(screen.getByLabelText('状态 page')).getByRole('button', { name: '删除状态' }),
  )
  expect(onUpdate.mock.calls[0][0].configuration).toMatchObject({ state: {}, update: {} })
})

it('switches condition-loop update modes and warns on incompatible literal types', async () => {
  const definition = addControlBlock(workflowDefinition, 'while')
  const base = definition.nodes.at(-1)!
  const node = {
    ...base,
    configuration: {
      ...base.configuration,
      state: { items: { kind: 'literal', value: [] } },
      update: {},
    },
  }
  const onUpdate = vi.fn()
  const props = {
    regions: definition.regions!,
    editable: true,
    onUpdate,
    onRegionUpdate: vi.fn(),
  }
  const view = render(<WorkflowControlFields node={node} {...props} />)
  await userEvent.click(screen.getByRole('combobox', { name: 'items 更新方式' }))
  await userEvent.click(screen.getByText('追加数组'))
  const appended = onUpdate.mock.calls.at(-1)![0]
  expect(appended.configuration.update.items).toEqual({
    kind: 'append',
    value: { kind: 'literal', value: null },
  })
  view.rerender(<WorkflowControlFields node={appended} {...props} />)
  await userEvent.click(screen.getByRole('combobox', { name: 'items 更新方式' }))
  await userEvent.click(screen.getByText('数值相加'))
  const added = onUpdate.mock.calls.at(-1)![0]
  expect(added.configuration.update.items).toEqual({
    kind: 'add',
    value: { kind: 'literal', value: 1 },
  })
  view.rerender(<WorkflowControlFields node={added} {...props} />)
  expect(screen.getByText('数值相加要求初始状态是数字。')).toBeVisible()
  await userEvent.click(screen.getByRole('combobox', { name: 'items 更新方式' }))
  await userEvent.click(screen.getByText('不更新'))
  expect(onUpdate.mock.calls.at(-1)![0].configuration.update).toEqual({})
})

it('edits a node-output source with an array index and keeps other state fields', async () => {
  const definition = addControlBlock(workflowDefinition, 'until')
  const base = definition.nodes.at(-1)!
  const node = {
    ...base,
    configuration: {
      ...base.configuration,
      state: { cursor: { kind: 'literal', value: null }, keep: { kind: 'literal', value: true } },
      update: {},
    },
  }
  const onUpdate = vi.fn()
  const props = {
    regions: definition.regions!,
    editable: true,
    onUpdate,
    onRegionUpdate: vi.fn(),
  }
  const view = render(<WorkflowControlFields node={node} {...props} />)
  await userEvent.click(screen.getByRole('combobox', { name: 'cursor 初始值 来源类型' }))
  await userEvent.click(screen.getByText('节点输出'))
  let changed = onUpdate.mock.calls.at(-1)![0]
  view.rerender(<WorkflowControlFields node={changed} {...props} />)
  fireEvent.change(screen.getByRole('textbox', { name: 'cursor 初始值 节点 ID' }), {
    target: { value: 'fetch' },
  })
  changed = onUpdate.mock.calls.at(-1)![0]
  view.rerender(<WorkflowControlFields node={changed} {...props} />)
  await userEvent.click(screen.getByRole('button', { name: '添加路径段' }))
  changed = onUpdate.mock.calls.at(-1)![0]
  view.rerender(<WorkflowControlFields node={changed} {...props} />)
  await userEvent.click(screen.getByRole('combobox', { name: 'cursor 初始值 路径 第 1 段类型' }))
  await userEvent.click(screen.getByText('数组索引'))
  changed = onUpdate.mock.calls.at(-1)![0]
  expect(changed.configuration.state).toEqual({
    cursor: { kind: 'node_output', node_id: 'fetch', path: [0] },
    keep: { kind: 'literal', value: true },
  })
})
