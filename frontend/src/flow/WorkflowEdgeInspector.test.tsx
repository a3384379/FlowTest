import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { workflowDefinition } from '../test/fixtures'
import WorkflowEdgeInspector from './WorkflowEdgeInspector'
import type { WorkflowEdge } from '../lib/api'
const mapped: WorkflowEdge = {
  ...workflowDefinition.edges[0],
  mappings: [
    {
      source: { node_id: 'start', path: 'body.id' },
      target: { node_id: 'api', location: 'body', key: 'id' },
      transform: { kind: 'json_parse', template: '{{value}}' },
    },
  ],
}
describe('edge configuration', () => {
  it('edits only the chosen mapping and retains its transform and edge identity', async () => {
    const update = vi.fn()
    const remove = vi.fn()
    const user = userEvent.setup()
    render(
      <WorkflowEdgeInspector
        edge={mapped}
        definition={workflowDefinition}
        editable
        onUpdate={update}
        onDelete={remove}
        onSwap={vi.fn()}
      />,
    )
    fireEvent.change(screen.getByLabelText('映射源表达式'), { target: { value: 'body.user.id' } })
    expect(update.mock.calls[0][0].mappings[0].transform).toEqual(mapped.mappings[0].transform)
    expect(update.mock.calls[0][0].id).toBe(mapped.id)
    fireEvent.change(screen.getByLabelText('映射目标字段'), { target: { value: 'user_id' } })
    await user.click(screen.getByRole('button', { name: '添加映射' }))
    expect(update.mock.calls.at(-1)![0].mappings).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: '删除映射' }))
    expect(update.mock.calls.at(-1)![0].mappings).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: '删除连线' }))
    expect(remove).toHaveBeenCalledTimes(1)
  })
  it('keeps unsupported targets and readonly conditions inspectable without writes', () => {
    const update = vi.fn()
    const swap = vi.fn()
    const view = render(
      <WorkflowEdgeInspector
        edge={{ ...mapped, condition: 'true', target: 'end' }}
        definition={workflowDefinition}
        editable={false}
        onUpdate={update}
        onDelete={vi.fn()}
        onSwap={swap}
      />,
    )
    expect(screen.getByText('条件为真')).toBeVisible()
    expect(screen.getByLabelText('映射源表达式')).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '交换真假分支' }))
    expect(swap).not.toHaveBeenCalled()
    view.rerender(
      <WorkflowEdgeInspector
        edge={{ ...mapped, condition: 'false', source: 'missing', target: 'missing-target' }}
        definition={workflowDefinition}
        editable
        onUpdate={update}
        onDelete={vi.fn()}
        onSwap={swap}
      />,
    )
    expect(screen.getByText('条件为假')).toBeVisible()
    expect(screen.getByRole('button', { name: '添加映射' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '交换真假分支' }))
    expect(swap).toHaveBeenCalledTimes(1)
  })
})
