import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import AssertionEvidence from './AssertionEvidence'
import { reportAssertionEvidence } from './assertion-model'

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
