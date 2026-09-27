import { describe, expect, it } from 'vitest'
import {
  addCondition,
  defaultCondition,
  parseCondition,
  removeCondition,
  replaceCondition,
} from './control-condition'

describe('control condition editor contract', () => {
  it('reads a strict nested expression and rejects missing operands or excessive depth', () => {
    const source = {
      kind: 'all',
      conditions: [
        {
          kind: 'compare',
          left: { kind: 'variable', scope: 'runtime', path: ['status'] },
          operator: 'equals',
          right: { kind: 'literal', value: 'ready' },
        },
        {
          kind: 'not',
          condition: {
            kind: 'compare',
            left: { kind: 'variable', scope: 'runtime', path: ['error'] },
            operator: 'exists',
          },
        },
      ],
    }
    expect(parseCondition(source)).toEqual(source)
    expect(
      parseCondition({ ...source, conditions: [{ kind: 'compare', operator: 'equals' }] }),
    ).toBeNull()
    expect(
      parseCondition({
        kind: 'compare',
        left: { kind: 'literal', value: 1 },
        operator: 'exists',
        right: { kind: 'literal', value: 2 },
      }),
    ).toBeNull()
    let tooDeep: unknown = defaultCondition()
    for (let index = 0; index < 8; index++) tooDeep = { kind: 'not', condition: tooDeep }
    expect(parseCondition(tooDeep)).toBeNull()
    expect(
      parseCondition({
        kind: 'all',
        conditions: Array.from({ length: 100 }, () => ({
          kind: 'all',
          conditions: [defaultCondition(), defaultCondition()],
        })),
      }),
    ).toBeNull()
  })

  it('edits one nested branch while preserving its siblings and a nonempty group', () => {
    const root = {
      kind: 'all' as const,
      conditions: [defaultCondition(), { kind: 'not' as const, condition: defaultCondition() }],
    }
    const changed = replaceCondition(root, [1, 0], {
      kind: 'compare',
      left: { kind: 'literal', value: 'done' },
      operator: 'not_empty',
    })
    if (changed.kind !== 'all') throw new Error('group kind changed')
    expect(changed.conditions[0]).toEqual(root.conditions[0])
    expect(changed.conditions[1]).toMatchObject({
      kind: 'not',
      condition: { operator: 'not_empty' },
    })
    const appended = addCondition(changed, [])
    if (appended.kind !== 'all') throw new Error('group kind changed')
    expect(appended.conditions).toHaveLength(3)
    const removed = removeCondition(appended, [1])
    if (removed.kind !== 'all') throw new Error('group kind changed')
    expect(removed.conditions).toHaveLength(2)
    expect(removeCondition({ kind: 'all', conditions: [defaultCondition()] }, [0])).toEqual({
      kind: 'all',
      conditions: [defaultCondition()],
    })
  })
})
