import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { WorkflowDefinition } from '../lib/api'
import WorkflowNodeRelations from './WorkflowNodeRelations'

const definition: WorkflowDefinition = {
  schema_version: '1.0',
  variables: {},
  nodes: [
    { id: 'source', type: 'start', name: '开始', position: { x: 0, y: 0 }, config: {} },
    { id: 'target', type: 'end', name: '结束', position: { x: 260, y: 0 }, config: {} },
  ],
  edges: [{ id: 'edge', source: 'source', target: 'target', condition: null, mappings: [] }],
  settings: { fail_fast: true, concurrency: 20, default_timeout_seconds: 30 },
}

describe('workflow definition relations', () => {
  it('shows separate source paths, loop scope and unresolved bindings without clickable guessed nodes', () => {
    const locate = vi.fn()
    const target = {
      ...definition.nodes[1]!,
      type: 'capability' as const,
      capability_id: 'flow.control.group',
      configuration: {
        inputs: {
          first: { kind: 'node_output', node_id: 'source', path: ['body', 'first'] },
          second: { kind: 'node_output', node_id: 'source', path: ['body', 'second'] },
          amount: { kind: 'variable', scope: 'loop', path: ['item', 'amount'] },
          missing: { kind: 'node_output', node_id: 'gone', path: ['body'] },
        },
      },
      bindings: [{ input: 'token', expression: '{{unknown.token}}' }],
    }
    render(<WorkflowNodeRelations node={target} definition={definition} onLocateNode={locate} />)
    expect(screen.getByText('$.body.first')).toBeVisible()
    expect(screen.getByText('$.body.second')).toBeVisible()
    expect(screen.getByText('$.inputs.second')).toBeVisible()
    expect(screen.getByText('循环变量 · loop')).toBeVisible()
    expect(screen.getByText('$.item.amount')).toBeVisible()
    expect(screen.getByText('来源节点不存在')).toBeVisible()
    expect(screen.getByText('表达式未解析')).toBeVisible()
    expect(screen.getByText('{{unknown.token}}')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'gone' })).not.toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '开始' })[1]!)
    expect(locate).toHaveBeenCalledWith('source')
  })
  it.each([undefined, null])('does not infer a branch when condition is %s', (condition) => {
    const locate = vi.fn()
    // Exercise the HTTP shape with an omitted property as well as explicit null.
    const serializedDefinition: WorkflowDefinition = JSON.parse(
      JSON.stringify({ ...definition, edges: [{ ...definition.edges[0]!, condition }] }),
    )
    render(
      <WorkflowNodeRelations
        node={definition.nodes[0]!}
        definition={serializedDefinition}
        onLocateNode={locate}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /^结束$/ }))
    expect(locate).toHaveBeenCalledWith('target')
    expect(screen.queryByText(/条件.*分支/)).not.toBeInTheDocument()
  })

  it.each([
    ['true', '条件成立分支'],
    ['false', '条件不成立分支'],
  ] as const)('labels the explicit %s branch from the definition', (condition, label) => {
    render(
      <WorkflowNodeRelations
        node={definition.nodes[0]!}
        definition={{ ...definition, edges: [{ ...definition.edges[0]!, condition }] }}
        onLocateNode={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: `结束 · ${label}` })).toBeVisible()
  })
})
