import { describe, expect, it } from 'vitest'
import { changeFields, proposedDraft } from './ai-change-diff'

describe('frozen draft review', () => {
  it('preserves omitted and null update fields while replacing a provided definition', () => {
    const before = {
      name: '原流程',
      description: '保持说明',
      definition: { nodes: [{ id: 'old' }], edges: ['old'] },
    }
    const patch = { name: '修改流程', description: null, definition: { nodes: [{ id: 'new' }] } }
    const after = proposedDraft(before, patch)
    expect(after.description).toBe('保持说明')
    expect(changeFields(before, after)).toEqual([
      { path: '$.name', before: '原流程', after: '修改流程' },
      { path: '$.definition.nodes', before: [{ id: 'old' }], after: [{ id: 'new' }] },
      { path: '$.definition.edges', before: ['old'], after: undefined },
    ])
    expect(before.definition.nodes[0].id).toBe('old')
  })
})
