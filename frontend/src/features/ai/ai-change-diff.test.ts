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
    const after = proposedDraft(before, patch, 'workflow')
    expect(after.description).toBe('保持说明')
    expect(changeFields(before, after)).toEqual([
      { path: '$.name', before: '原流程', after: '修改流程' },
      { path: '$.definition.nodes', before: [{ id: 'old' }], after: [{ id: 'new' }] },
      { path: '$.definition.edges', before: ['old'], after: undefined },
    ])
    expect(before.definition.nodes[0].id).toBe('old')
  })

  it('keeps omitted test-case runtime maps and replaces explicitly supplied maps', () => {
    const before = {
      name: '原用例',
      definition: {
        workflow_id: 'workflow-1',
        environment_id: 'environment-1',
        runtime_variables: { region: 'cn-north' },
        runtime_headers: { 'X-Region': 'cn-north' },
      },
    }
    const after = proposedDraft(
      before,
      { definition: { workflow_id: 'workflow-1', environment_id: 'environment-2' } },
      'test_case',
    )
    expect(after.definition).toEqual({ ...before.definition, environment_id: 'environment-2' })
    expect(changeFields(before, after)).toEqual([
      { path: '$.definition.environment_id', before: 'environment-1', after: 'environment-2' },
    ])
    const cleared = proposedDraft(
      before,
      { definition: { ...before.definition, runtime_variables: {}, runtime_headers: {} } },
      'test_case',
    )
    expect(cleared.definition).toMatchObject({ runtime_variables: {}, runtime_headers: {} })
    expect(before.definition.runtime_variables).toEqual({ region: 'cn-north' })
  })

  it('preserves workflow variables and omitted node config by identity without reviving deleted nodes', () => {
    const before = {
      definition: {
        variables: { region: 'cn-north' },
        nodes: [
          { id: 'first', name: '原节点', config: { expected: 200 } },
          { id: 'second', config: { expected: 201 } },
          { id: 'removed', config: { expected: 202 } },
        ],
        edges: ['old'],
      },
    }
    const after = proposedDraft(
      before,
      {
        definition: {
          nodes: [
            { id: 'second', config: {} },
            { id: 'first', name: '新节点' },
            { id: 'new', config: { expected: 204 } },
          ],
          edges: ['new'],
        },
      },
      'workflow',
    )
    expect(after.definition).toEqual({
      variables: { region: 'cn-north' },
      nodes: [
        { id: 'second', config: {} },
        { id: 'first', name: '新节点', config: { expected: 200 } },
        { id: 'new', config: { expected: 204 } },
      ],
      edges: ['new'],
    })
    expect(
      proposedDraft(before, { definition: { variables: {}, nodes: [] } }, 'workflow').definition,
    ).toEqual({ variables: {}, nodes: [] })
    expect(before.definition.nodes).toHaveLength(3)
  })

  it('keeps explicitly provided literal placeholders without scanning or substituting them', () => {
    const before = {
      definition: { runtime_variables: { region: 'old-region' }, runtime_headers: {} },
    }
    const after = proposedDraft(
      before,
      { definition: { runtime_variables: { region: '[REDACTED]' } } },
      'test_case',
    )
    expect(after.definition).toEqual({
      runtime_variables: { region: '[REDACTED]' },
      runtime_headers: {},
    })
  })
})
