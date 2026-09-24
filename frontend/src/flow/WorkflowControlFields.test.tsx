import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { workflowDefinition } from '../test/fixtures'
import { addControlBlock } from './editor/control-blocks'
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
