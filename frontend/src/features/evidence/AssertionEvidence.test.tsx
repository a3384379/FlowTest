import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import AssertionEvidence from './AssertionEvidence'
import { reportAssertionEvidence, workflowAssertionEvidence } from './assertion-model'

it('shows failed assertions first and preserves false, zero, null and missing values', () => {
  render(
    <AssertionEvidence
      items={[
        { name: '空值校验', passed: true, expected: null, actual: null },
        { name: '金额校验', passed: false, expected: 0, actual: false, message: '类型不一致' },
        { name: '缺失证据', passed: null, expected: undefined, actual: undefined },
      ]}
    />,
  )
  const cards = within(screen.getByLabelText('断言证据')).getAllByRole('article')
  expect(within(cards[0]).getByText('金额校验')).toBeVisible()
  expect(within(cards[0]).getByText('0')).toBeVisible()
  expect(within(cards[0]).getByText('false')).toBeVisible()
  expect(within(cards[1]).getAllByText('null')).toHaveLength(2)
  expect(within(cards[2]).getByText('未提供结果')).toBeVisible()
  expect(within(cards[2]).getAllByText('未提供')).toHaveLength(2)
})

it('keeps incomplete report assertions unknown and does not invent evidence from arbitrary payloads', () => {
  expect(reportAssertionEvidence({ expected: 0 }, '金额')).toEqual([
    { name: '金额', passed: null, expected: 0, actual: undefined, message: undefined },
  ])
  expect(reportAssertionEvidence({ result: 'passed' }, '金额')).toEqual([])
})

it('derives numeric differences from frozen values and identifies the actual evidence owner', () => {
  render(
    <AssertionEvidence
      source="订单断言 (assert-order)"
      items={[
        { name: '金额校验', passed: false, expected: 29900, actual: 29901 },
        { name: '零值校验', passed: true, expected: 0, actual: 0 },
        { name: '状态校验', passed: false, expected: 'paid', actual: 'pending' },
      ]}
    />,
  )
  expect(screen.getByText('差值（实际 − 期望）：+1 · 单位：未提供')).toBeVisible()
  expect(screen.getByText('差值（实际 − 期望）：0 · 单位：未提供')).toBeVisible()
  expect(screen.getAllByText('证据来源：订单断言 (assert-order)')).toHaveLength(3)
})

it('reads frozen standalone assertion output and keeps standard assertions authoritative', () => {
  const output = { passed: false, actual: 200, expected: 201, operator: 'equals' }
  const node = { node_type: 'assert', name: '状态码断言', output }
  expect(workflowAssertionEvidence(node)).toEqual([
    { name: node.name, passed: false, actual: 200, expected: 201, message: undefined },
  ])
  const standard = { name: '标准证据', passed: false, actual: false, expected: 0 }
  expect(workflowAssertionEvidence({ ...node, result: { assertions: [standard] } })).toEqual([
    { ...standard, message: undefined },
  ])
  expect(workflowAssertionEvidence({ ...node, node_type: 'api' })).toEqual([])
  expect(workflowAssertionEvidence({ ...node, output: { passed: false } })).toEqual([])
})
