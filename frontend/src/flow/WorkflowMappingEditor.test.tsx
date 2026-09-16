import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { WorkflowDefinition, WorkflowFieldMapping } from '../lib/api'
import { workflowDefinition } from '../test/fixtures'
import MappingEditor from './WorkflowMappingEditor'
import { useWorkflowEditor } from './editor/use-workflow-editor'

const mapping: WorkflowFieldMapping = {
  source: { node_id: 'start', path: 'body' },
  target: { node_id: 'api', location: 'body', key: 'value' },
  transform: { kind: 'json_parse', template: '{{value}}' },
}
describe('mapping focus transactions', () => {
  it('keeps 80 keystrokes, another row, and deletion in independent undo entries', async () => {
    const changed = vi.fn()
    const user = userEvent.setup()
    render(<HistoryHarness changed={changed} />)
    const first = screen.getAllByLabelText('映射源表达式')[0]
    await user.click(first)
    await user.clear(first)
    await user.type(first, 'x'.repeat(80))
    expect(changed).not.toHaveBeenCalled()
    await user.click(screen.getAllByLabelText('映射源表达式')[1])
    expect(changed).toHaveBeenCalledTimes(1)
    const second = screen.getAllByLabelText('映射源表达式')[1]
    await user.clear(second)
    await user.type(second, 'body.other')
    await user.click(screen.getAllByRole('button', { name: '删除映射' })[0])
    expect(changed).toHaveBeenCalledTimes(3)
    await user.click(screen.getByText('Undo'))
    expect(screen.getAllByLabelText('映射源表达式')[0]).toHaveValue('x'.repeat(80))
    expect(screen.getAllByLabelText('映射源表达式')[1]).toHaveValue('body.other')
    expect(
      JSON.parse(screen.getByTestId('definition').textContent!).edges[0].mappings[0],
    ).toMatchObject({
      transform: mapping.transform,
      source: { node_id: 'start' },
      target: mapping.target,
    })
    await user.click(screen.getByText('Undo'))
    expect(screen.getAllByLabelText('映射源表达式')[1]).toHaveValue('body')
    await user.click(screen.getByText('Undo'))
    expect(screen.getAllByLabelText('映射源表达式')[0]).toHaveValue('body')
    await user.click(screen.getByText('Redo'))
    expect(screen.getAllByLabelText('映射源表达式')[0]).toHaveValue('x'.repeat(80))
  })
  it('commits Enter once, cancels Escape, and does not take over IME Enter', () => {
    const changed = vi.fn()
    render(<HistoryHarness changed={changed} />)
    const field = screen.getAllByLabelText('映射目标字段')[0]
    field.focus()
    fireEvent.change(field, { target: { value: 'pending' } })
    fireEvent.keyDown(field, { key: 'Enter', isComposing: true })
    expect(changed).not.toHaveBeenCalled()
    fireEvent.keyDown(field, { key: 'Escape' })
    expect(field).toHaveValue('value')
    expect(changed).not.toHaveBeenCalled()
    field.focus()
    fireEvent.change(field, { target: { value: 'accepted' } })
    fireEvent.keyDown(field, { key: 'Enter' })
    fireEvent.blur(field)
    expect(changed).toHaveBeenCalledTimes(1)
    expect(field).toHaveValue('accepted')
  })
})
function HistoryHarness({ changed }: { changed: (value: WorkflowDefinition) => void }) {
  const [definition, setDefinition] = useState<WorkflowDefinition>({
    ...workflowDefinition,
    edges: [
      {
        ...workflowDefinition.edges[0],
        mappings: [structuredClone(mapping), structuredClone(mapping)],
      },
    ],
  })
  const editor = useWorkflowEditor(definition, true, (next) => {
    setDefinition(next)
    changed(next)
  })
  const edge = editor.definition.edges[0]
  return (
    <>
      {edge.mappings.map((item, index) => (
        <MappingEditor
          key={index}
          mapping={item}
          editable
          onUpdate={(next) =>
            editor.commit({
              ...editor.definition,
              edges: [
                { ...edge, mappings: edge.mappings.map((old, i) => (i === index ? next : old)) },
              ],
            })
          }
          onDelete={() =>
            editor.commit({
              ...editor.definition,
              edges: [{ ...edge, mappings: edge.mappings.filter((_, i) => i !== index) }],
            })
          }
        />
      ))}
      <button onClick={editor.undo}>Undo</button>
      <button onClick={editor.redo}>Redo</button>
      <output data-testid="definition">{JSON.stringify(editor.definition)}</output>
    </>
  )
}
