import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DraftContext, DraftSession } from '../features/drafts/draft-session'
import { workflowDefinition } from '../test/fixtures'
import type { WorkflowDefinition } from '../lib/api'
import WorkflowNodeEditSession from './WorkflowNodeEditSession'
import WorkflowJsonInput from './WorkflowJsonInput'
import WorkflowControlFields from './WorkflowControlFields'
import { addControlBlock } from './editor/control-blocks'
import { editorNode, restoreEditedNode } from './editor/graph-analysis'

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
            <button onClick={() => update(addControlBlock(definition, 'group'), 'structure')}>
              添加控制结构
            </button>
            {(['edit', 'add', 'delete'] as const).map((operation) => (
              <button
                key={operation}
                onClick={() =>
                  update(
                    {
                      ...definition,
                      edges: definition.edges.map((edge, index) =>
                        index === 0
                          ? {
                              ...edge,
                              mappings:
                                operation === 'delete'
                                  ? []
                                  : [
                                      ...(operation === 'add' ? edge.mappings : []),
                                      {
                                        transform: { kind: 'identity' as const, template: '' },
                                        source: { node_id: edge.source, path: operation },
                                        target: {
                                          node_id: edge.target,
                                          location: 'body',
                                          key: 'value',
                                        },
                                      },
                                    ],
                            }
                          : edge,
                      ),
                    },
                    'edges',
                  )
                }
              >
                {operation} mapping
              </button>
            ))}
            <input
              aria-label="节点名称"
              value={draft.name}
              onChange={(event) =>
                update(
                  {
                    ...definition,
                    nodes: definition.nodes.map((item) =>
                      item.id === draft.id
                        ? restoreEditedNode(draft, {
                            ...editorNode(draft),
                            name: event.target.value,
                          })
                        : item,
                    ),
                  },
                  'node',
                )
              }
            />
            <label>
              请求 JSON
              <WorkflowJsonInput
                fieldKey="payload"
                value={editorNode(draft).config.payload ?? {}}
                editable
                onChange={(payload) =>
                  update(
                    {
                      ...definition,
                      nodes: definition.nodes.map((item) =>
                        item.id === draft.id
                          ? restoreEditedNode(draft, {
                              ...editorNode(draft),
                              config: { ...editorNode(draft).config, payload },
                            })
                          : item,
                      ),
                    },
                    'node',
                  )
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
  it('blocks an atomic structure change until the selected node draft is applied', () => {
    const changed = vi.fn()
    render(<Harness session={new DraftSession()} changed={changed} />)
    fireEvent.change(screen.getByRole('textbox', { name: '节点名称' }), {
      target: { value: '暂存名称' },
    })
    fireEvent.click(screen.getByRole('button', { name: '添加控制结构' }))
    expect(changed).not.toHaveBeenCalled()
    expect(screen.getByText(/请先应用或丢弃当前节点配置/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    fireEvent.click(screen.getByRole('button', { name: '添加控制结构' }))
    expect(changed.mock.calls.at(-1)![0].regions).toHaveLength(1)
  })
  it('clears an abandoned control JSON draft and retains only applied configuration edits', () => {
    const definition = addControlBlock(workflowDefinition, 'repeat')
    const node = definition.nodes.at(-1)!
    const session = new DraftSession()
    const changed = vi.fn()
    render(
      <DraftContext.Provider value={session}>
        <WorkflowNodeEditSession
          scope="control:"
          node={node}
          definition={definition}
          editable
          onChange={changed}
        >
          {(draft, update) => (
            <WorkflowControlFields
              node={draft}
              regions={definition.regions!}
              editable
              onUpdate={(updated) =>
                update(
                  {
                    ...definition,
                    nodes: definition.nodes.map((item) => (item.id === node.id ? updated : item)),
                  },
                  'node',
                )
              }
              onRegionUpdate={vi.fn()}
            />
          )}
        </WorkflowNodeEditSession>
      </DraftContext.Provider>,
    )
    const editor = screen.getByRole('textbox', { name: '控制块配置 JSON' })
    fireEvent.change(editor, { target: { value: '[' } })
    expect(session.nodeEditors.size).toBe(1)
    expect(screen.getByText('配置尚未应用')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '丢弃配置草稿' }))
    expect(session.nodeEditors.size).toBe(0)
    expect(screen.getByText('配置已应用到本地流程')).toBeVisible()
    fireEvent.change(editor, { target: { value: '{"count":4}' } })
    fireEvent.click(screen.getByRole('button', { name: '应用配置' }))
    expect(session.nodeEditors.size).toBe(1)
    const pending = [...session.nodeEditors.values()][0]
    expect(pending.rawFields).toEqual({})
    expect(pending.draftNode.configuration).toEqual({ count: 4 })
    expect(changed).not.toHaveBeenCalled()
  })
  it('keeps a condition-loop literal draft across remount and blocks node Apply until value Apply', () => {
    const definition = addControlBlock(workflowDefinition, 'while')
    const original = definition.nodes.at(-1)!
    const node = {
      ...original,
      configuration: {
        ...original.configuration,
        state: { page: { kind: 'literal', value: 0 } },
        update: { page: { kind: 'add', value: { kind: 'literal', value: 1 } } },
      },
    }
    const configured = {
      ...definition,
      nodes: definition.nodes.map((item) => (item.id === node.id ? node : item)),
    }
    const session = new DraftSession()
    const changed = vi.fn()
    function view() {
      return render(
        <DraftContext.Provider value={session}>
          <WorkflowNodeEditSession
            scope="state:"
            node={node}
            definition={configured}
            editable
            onChange={changed}
          >
            {(draft, update) => (
              <WorkflowControlFields
                node={draft}
                regions={configured.regions!}
                editable
                onUpdate={(updated) =>
                  update(
                    {
                      ...configured,
                      nodes: configured.nodes.map((item) => (item.id === node.id ? updated : item)),
                    },
                    'node',
                  )
                }
                onRegionUpdate={vi.fn()}
              />
            )}
          </WorkflowNodeEditSession>
        </DraftContext.Provider>,
      )
    }
    const first = view()
    fireEvent.change(screen.getByRole('textbox', { name: 'page 初始值 JSON 值' }), {
      target: { value: '2' },
    })
    expect(session.nodeEditors.size).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    expect(changed).not.toHaveBeenCalled()
    first.unmount()
    view()
    expect(screen.getByRole('textbox', { name: 'page 初始值 JSON 值' })).toHaveValue('2')
    fireEvent.click(
      within(screen.getByLabelText('page 初始值')).getByRole('button', { name: '应用值' }),
    )
    expect([...session.nodeEditors.values()][0].rawFields).toEqual({})
    expect([...session.nodeEditors.values()][0].draftNode.configuration?.state).toEqual({
      page: { kind: 'literal', value: 2 },
    })
  })
  it.each(['api', 'capability'] as const)(
    'keeps the last input when a %s node name returns to its applied value',
    (type) => {
      const base = workflowDefinition.nodes[1]
      const original =
        type === 'api'
          ? base
          : {
              ...base,
              type: 'capability' as const,
              capability_id: 'http.request',
              capability_version: '2.0.0',
              configuration: base.config,
              config: { legacy: true },
            }
      const initial = {
        ...workflowDefinition,
        nodes: workflowDefinition.nodes.map((item) => (item.id === base.id ? original : item)),
      }
      const session = new DraftSession()
      const changed = vi.fn()
      render(<Harness session={session} changed={changed} external={initial} />)

      fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: '等待2' } })
      fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: base.name } })

      expect(screen.getByLabelText('节点名称')).toHaveValue(base.name)
      expect([...session.nodeEditors.values()][0].draftNode.name).toBe(base.name)
      expect(session.unsafe.size).toBe(0)
      expect(screen.getByRole('button', { name: '丢弃修改' })).toBeDisabled()
      fireEvent.change(screen.getByLabelText(/请求 JSON/), {
        target: { value: '{"saved":true}' },
      })
      fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
      expect(changed).toHaveBeenCalledTimes(1)
      expect(changed.mock.calls[0][0].nodes[1]).toMatchObject({ name: base.name, type })
    },
  )
  it.each(['edit', 'add', 'delete'] as const)(
    'preserves unapplied node fields during %s mapping',
    async (operation) => {
      const changed = vi.fn()
      render(
        <Harness
          session={new DraftSession()}
          changed={changed}
          external={{
            ...workflowDefinition,
            edges: workflowDefinition.edges.map((edge, index) =>
              index === 0
                ? {
                    ...edge,
                    mappings: [
                      {
                        transform: { kind: 'identity' as const, template: '' },
                        source: { node_id: edge.source, path: 'body' },
                        target: { node_id: edge.target, location: 'body', key: 'value' },
                      },
                    ],
                  }
                : edge,
            ),
          }}
        />,
      )
      fireEvent.change(screen.getByLabelText('节点名称'), { target: { value: '未应用名称' } })
      fireEvent.change(screen.getByLabelText(/请求 JSON/), {
        target: { value: '{"pending":true}' },
      })
      fireEvent.click(screen.getByRole('button', { name: `${operation} mapping` }))
      expect(screen.getByLabelText('节点名称')).toHaveValue('未应用名称')
      expect(screen.getByLabelText(/请求 JSON/)).toHaveValue('{"pending":true}')
      expect(changed).toHaveBeenCalledTimes(1)
      expect(changed.mock.calls[0][0].nodes).toEqual(workflowDefinition.nodes)
      fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
      await waitFor(() => expect(changed).toHaveBeenCalledTimes(2))
      expect(changed.mock.calls[1][0].nodes[1]).toMatchObject({
        name: '未应用名称',
        config: { payload: { pending: true } },
      })
      expect(changed.mock.calls[1][0].edges).toEqual(changed.mock.calls[0][0].edges)
    },
  )
  it('retains an unfinished JSON input when an edge changes', () => {
    const session = new DraftSession()
    const changed = vi.fn()
    render(<Harness session={session} changed={changed} />)
    fireEvent.change(screen.getByLabelText(/请求 JSON/), { target: { value: '{"pending":' } })
    fireEvent.click(screen.getByRole('button', { name: 'add mapping' }))

    expect(screen.getByLabelText(/请求 JSON/)).toHaveValue('{"pending":')
    expect([...session.nodeEditors.values()][0].rawFields.payload).toMatchObject({
      text: '{"pending":',
      error: '请检查引号、逗号与括号是否完整。',
    })
    expect(changed).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '应用节点配置' }))
    expect(changed).toHaveBeenCalledTimes(1)
  })
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
