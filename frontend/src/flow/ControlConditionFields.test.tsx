import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import ControlConditionFields from './ControlConditionFields'
import { defaultCondition, type ConditionExpression } from './editor/control-condition'

it('builds a nested condition and removes the unused right operand for a unary operator', async () => {
  const onChange = vi.fn()
  function Harness() {
    const [condition, setCondition] = useState<ConditionExpression>(defaultCondition())
    return (
      <ControlConditionFields
        label="判断条件"
        value={condition}
        choices={[]}
        editable
        onChange={(next) => {
          onChange(next)
          setCondition(next)
        }}
      />
    )
  }
  render(<Harness />)
  await userEvent.click(screen.getByRole('combobox', { name: '判断条件 组合方式' }))
  await userEvent.click(screen.getByText('全部满足'))
  await userEvent.click(screen.getByRole('button', { name: '添加比较条件' }))
  await userEvent.click(screen.getByRole('combobox', { name: '判断条件 第 1 项 组合方式' }))
  await userEvent.click(screen.getAllByText('取反').at(-1)!)
  await userEvent.click(screen.getByRole('combobox', { name: '判断条件 第 2 项 运算符' }))
  await userEvent.click(screen.getAllByText('存在').at(-1)!)
  expect(onChange.mock.calls.at(-1)![0]).toMatchObject({
    kind: 'all',
    conditions: [{ kind: 'not' }, { kind: 'compare', operator: 'exists' }],
  })
  expect(onChange.mock.calls.at(-1)![0].conditions[1].right).toBeUndefined()
})
