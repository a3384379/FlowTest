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
