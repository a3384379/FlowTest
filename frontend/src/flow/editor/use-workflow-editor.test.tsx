import { act, renderHook } from '@testing-library/react'
import { StrictMode, type ReactNode } from 'react'
import { expect, it, vi } from 'vitest'
import { workflowDefinition } from '../../test/fixtures'
import { useWorkflowEditor } from './use-workflow-editor'

it('SEL03/HIST01 merges 50 preview positions into one callback and restores on undo', () => {
  const onChange = vi.fn()
  const { result } = renderHook(() => useWorkflowEditor(workflowDefinition, true, onChange))
  act(() => result.current.click('node', 'api'))
  expect(onChange).not.toHaveBeenCalled()
  act(() => {
    result.current.beginDrag()
    for (let x = 0; x < 50; x++)
      result.current.positionsChanged([{ id: 'api', position: { x, y: 20 } }], true)
  })
  expect(onChange).not.toHaveBeenCalled()
  act(() => result.current.endDrag([{ id: 'api', position: { x: 80, y: 20 } }]))
  expect(onChange).toHaveBeenCalledTimes(1)
  expect(result.current.past).toHaveLength(1)
  act(() => result.current.undo())
  expect(onChange.mock.lastCall?.[0]).toEqual(workflowDefinition)
})
it('HIST03 cancels preview without a draft write', () => {
  const onChange = vi.fn()
  const { result } = renderHook(() => useWorkflowEditor(workflowDefinition, true, onChange))
  act(() => {
    result.current.beginDrag()
    result.current.positionsChanged([{ id: 'api', position: { x: 80, y: 20 } }], true)
    result.current.cancelDrag()
  })
  expect(onChange).not.toHaveBeenCalled()
  expect(result.current.positions.size).toBe(0)
})
it('HIST06/HIST10 keeps equivalent echoes and executes StrictMode commands exactly once', () => {
  const onChange = vi.fn()
  const { result, rerender } = renderHook(
    ({ definition }) => useWorkflowEditor(definition, true, onChange),
    {
      initialProps: { definition: workflowDefinition },
      wrapper: ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>,
    },
  )
  const next = { ...workflowDefinition, variables: { first: '1' } }
  act(() => {
    result.current.commit(next)
    result.current.commit({
      ...result.current.latest.current.definition,
      variables: { first: '1', second: '2' },
    })
  })
  expect(onChange).toHaveBeenCalledTimes(2)
  rerender({ definition: structuredClone(result.current.definition) })
  expect(result.current.past).toHaveLength(2)
})
it('KEY09 rejects commits and history changes in read-only mode', () => {
  const onChange = vi.fn()
  const { result } = renderHook(() => useWorkflowEditor(workflowDefinition, false, onChange))
  act(() => {
    result.current.commit({ ...workflowDefinition, edges: [] })
    result.current.undo()
    result.current.redo()
  })
  expect(onChange).not.toHaveBeenCalled()
})

it('ignores late pointer updates after cancellation and starts a fresh drag independently', () => {
  const onChange = vi.fn()
  const { result } = renderHook(() => useWorkflowEditor(workflowDefinition, true, onChange))
  act(() => {
    result.current.beginDrag()
    result.current.positionsChanged([{ id: 'api', position: { x: 100, y: 100 } }], true)
    result.current.cancelDrag()
    result.current.positionsChanged([{ id: 'api', position: { x: 400, y: 400 } }], true)
    result.current.endDrag([{ id: 'api', position: { x: 400, y: 400 } }])
  })
  expect(onChange).not.toHaveBeenCalled()
  act(() => {
    result.current.beginDrag()
    result.current.positionsChanged([{ id: 'api', position: { x: 600, y: 300 } }], false)
  })
  expect(onChange).toHaveBeenCalledTimes(1)
})
it('bounds history, truncates redo, and resets a stale drag on external replacement', async () => {
  const onChange = vi.fn()
  const { result, rerender } = renderHook(
    ({ definition }) => useWorkflowEditor(definition, true, onChange),
    { initialProps: { definition: workflowDefinition } },
  )
  act(() => {
    for (let index = 0; index < 60; index++)
      result.current.commit({
        ...result.current.latest.current.definition,
        variables: { index: String(index) },
      })
  })
  expect(result.current.past).toHaveLength(50)
  act(() => {
    result.current.undo()
    result.current.undo()
  })
  expect(result.current.future).toHaveLength(2)
  act(() =>
    result.current.commit({
      ...result.current.latest.current.definition,
      variables: { new: 'true' },
    }),
  )
  expect(result.current.future).toHaveLength(0)
  act(() => result.current.beginDrag())
  rerender({ definition: { ...workflowDefinition, variables: { external: 'true' } } })
  await act(async () => undefined)
  expect(result.current.past).toHaveLength(0)
  expect(result.current.dragging).toBe(false)
  expect(result.current.definition.variables).toEqual({ external: 'true' })
})
it('keeps node and edge selection mutually exclusive and prunes stale selection', async () => {
  const onChange = vi.fn()
  const { result, rerender } = renderHook(
    ({ definition }) => useWorkflowEditor(definition, true, onChange),
    { initialProps: { definition: workflowDefinition } },
  )
  act(() => {
    result.current.click('edge', workflowDefinition.edges[0].id)
    result.current.click('node', 'api')
  })
  expect(result.current.selection).toEqual({ kind: 'node', id: 'api' })
  rerender({
    definition: {
      ...workflowDefinition,
      nodes: workflowDefinition.nodes.filter((node) => node.id !== 'api'),
      edges: [],
    },
  })
  await act(async () => undefined)
  expect(result.current.selection).toBeNull()
  expect(onChange).not.toHaveBeenCalled()
  act(() => {
    result.current.undo()
    result.current.redo()
    result.current.accept({ kind: 'unchanged' })
    result.current.accept({
      kind: 'blocked',
      diagnostics: [{ code: 'blocked', message: '不可连接', severity: 'error' }],
    })
  })
  expect(result.current.message).toBe('不可连接')
})
it('protects boundary deletion and restores an ordinary edge through undo', () => {
  const onChange = vi.fn()
  const { result } = renderHook(() => useWorkflowEditor(workflowDefinition, true, onChange))
  act(() => {
    result.current.click('node', 'start')
    result.current.deleteSelection()
  })
  expect(onChange).not.toHaveBeenCalled()
  expect(result.current.message).toContain('跳过')
  act(() => {
    result.current.click('edge', workflowDefinition.edges[0].id)
    result.current.deleteSelection()
  })
  expect(result.current.definition.edges).toHaveLength(workflowDefinition.edges.length - 1)
  act(() => result.current.undo())
  expect(result.current.definition.edges).toEqual(workflowDefinition.edges)
})
