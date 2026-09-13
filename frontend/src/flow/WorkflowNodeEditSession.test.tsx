import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DraftContext, DraftSession } from '../features/drafts/draft-session'
import { workflowDefinition } from '../test/fixtures'
import type { WorkflowDefinition } from '../lib/api'
import WorkflowNodeEditSession from './WorkflowNodeEditSession'
import WorkflowJsonInput from './WorkflowJsonInput'

function Harness({
  session,
  changed,
  external = workflowDefinition,
}: {
  session: DraftSession
  changed: (value: WorkflowDefinition) => void
  external?: WorkflowDefinition
}) {
  const [definition, setDefinition] = useState(external)
  const node = definition.nodes[1]
  return (
    <DraftContext.Provider value={session}>
      <button onClick={() => setDefinition(external)}>撤销节点修改</button>
      <WorkflowNodeEditSession
        scope="test:"
        node={node}
        definition={definition}
        editable
        onChange={(next) => {
          changed(next)
          setDefinition(next)
        }}
      >
        {(draft, update) => (
          <>
            <input
              aria-label="节点名称"
              value={draft.name}
              onChange={(event) =>
                update({
                  ...definition,
                  nodes: definition.nodes.map((item) =>
                    item.id === draft.id ? { ...draft, name: event.target.value } : item,
                  ),
                })
              }
            />
            <label>
              请求 JSON
              <WorkflowJsonInput
                fieldKey="payload"
                value={draft.config.payload ?? {}}
                editable
                onChange={(payload) =>
                  update({
                    ...definition,
                    nodes: definition.nodes.map((item) =>
                      item.id === draft.id
                        ? { ...draft, config: { ...draft.config, payload } }
                        : item,
                    ),
                  })
                }
              />
            </label>
          </>
        )}
      </WorkflowNodeEditSession>
    </DraftContext.Provider>
  )
}
describe('node edit transactions', () => {
  it('rebases a clean form after undo and permits a subsequent edit', async () => {
    const changed = vi.fn()
    render(<Harness session={new DraftSession()} changed={changed} />)
    fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: '修改名称' } })
    fireEvent.change(screen.getByLabelText(/请求 JSON/), { target: { value: '{"updated":true}' } })
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    fireEvent.click(screen.getByRole('button', { name: '撤销节点修改' }))
    await waitFor(() =>
      expect(screen.getByLabelText('节点名称')).toHaveValue(workflowDefinition.nodes[1].name),
    )
    expect(screen.getByLabelText(/请求 JSON/)).toHaveValue('{}')
    fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: '再次编辑' } })
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    expect(changed).toHaveBeenCalledTimes(2)
    expect(changed.mock.lastCall?.[0].nodes[1].name).toBe('再次编辑')
  })
  it('keeps field edits off the graph until Apply and commits once', async () => {
    const session = new DraftSession()
    const changed = vi.fn()
    render(<Harness session={session} changed={changed} />)
    fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: '更新后的节点' } })
    expect(changed).not.toHaveBeenCalled()
    expect(session.unsafe.size).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    expect(changed).toHaveBeenCalledTimes(1)
    expect(changed.mock.calls[0][0].nodes[1].name).toBe('更新后的节点')
    expect(session.unsafe.size).toBe(0)
  })
  it('retains invalid raw JSON and name across remount, blocks Apply, and releases only its unsafe key', () => {
    const session = new DraftSession()
    session.markUnsafe('other-resource', true)
    const changed = vi.fn()
    const view = render(<Harness session={session} changed={changed} />)
    fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: '会话名称' } })
    fireEvent.change(screen.getByLabelText(/请求 JSON/), { target: { value: '{"unfinished":' } })
    expect(screen.getByRole('alert')).toHaveTextContent(
      'JSON 格式错误：请检查引号、逗号与括号是否完整。',
    )
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    expect(changed).not.toHaveBeenCalled()
    expect(screen.getByText(/请检查节点名称与 JSON/)).toBeVisible()
    view.unmount()
    render(<Harness session={session} changed={changed} />)
    expect(screen.getByLabelText(/请求 JSON/)).toHaveValue('{"unfinished":')
    expect(screen.getByLabelText('节点名称')).toHaveValue('会话名称')
    fireEvent.change(screen.getByLabelText(/请求 JSON/), { target: { value: '{"ready":true}' } })
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    expect(changed).toHaveBeenCalledTimes(1)
    expect(session.unsafe).toEqual(new Set(['other-resource']))
  })
  it('refuses to overwrite a content conflict but merges a newer position', () => {
    const session = new DraftSession()
    const changed = vi.fn()
    const first = render(<Harness session={session} changed={changed} />)
    fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: '本地名称' } })
    first.unmount()
    const moved = {
      ...workflowDefinition,
      nodes: workflowDefinition.nodes.map((node) => ({ ...node, position: { x: 900, y: 600 } })),
    }
    const second = render(<Harness session={session} changed={changed} external={moved} />)
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    expect(changed.mock.calls[0][0].nodes[1].position).toEqual({ x: 900, y: 600 })
    fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: '再次修改' } })
    second.unmount()
    render(
      <Harness
        session={session}
        changed={changed}
        external={{ ...moved, nodes: moved.nodes.map((node) => ({ ...node, name: '服务器名称' })) }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    expect(changed).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/节点内容已从外部更新/)).toBeVisible()
  })
})
