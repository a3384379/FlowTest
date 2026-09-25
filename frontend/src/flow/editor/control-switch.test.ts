import { expect, it } from 'vitest'
import { switchToRules, switchToValue } from './control-switch'

const configuration = {
  mode: 'value',
  value: { kind: 'variable', scope: 'runtime', path: ['status'] },
  branches: [
    {
      id: 'ok',
      label: '成功',
      body: { kind: 'inline', region_id: 'r1' },
      match: { kind: 'literal', value: 'ok' },
    },
    {
      id: 'fail',
      label: '失败',
      body: { kind: 'inline', region_id: 'r2' },
      match: { kind: 'literal', value: 'fail' },
    },
  ],
  default: { behavior: 'skip' },
  inputs: { status: { kind: 'literal', value: 'ok' } },
}

it('converts a value switch to rules and back without losing branch identities or policy', () => {
  const rules = switchToRules(configuration)!
  expect(rules).toMatchObject({
    mode: 'rules',
    value: null,
    branches: [
      { id: 'ok', match: null, condition: { kind: 'compare', operator: 'equals' } },
      { id: 'fail', match: null, condition: { kind: 'compare', operator: 'equals' } },
    ],
    default: configuration.default,
    inputs: configuration.inputs,
  })
  expect(switchToValue(rules)).toEqual(configurationWithNullConditions())
})

it('refuses to flatten complex rules into value matching', () => {
  const rules = switchToRules(configuration)!
  const branches = rules.branches as Record<string, unknown>[]
  expect(
    switchToValue({
      ...rules,
      branches: [
        { ...branches[0], condition: { kind: 'not', condition: branches[0].condition } },
        branches[1],
      ],
    }),
  ).toBeNull()
})

function configurationWithNullConditions() {
  return {
    ...configuration,
    branches: configuration.branches.map((branch) => ({ ...branch, condition: null })),
  }
}
