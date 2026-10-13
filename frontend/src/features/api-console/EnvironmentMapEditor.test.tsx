import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it } from 'vitest'

import EnvironmentMapEditor from './EnvironmentMapEditor'
import { mapValue, type EnvironmentMapValue } from './environment-map'

it('clears a failed conversion message after correcting a table row', async () => {
  function Editor() {
    const [value, setValue] = useState<EnvironmentMapValue>(mapValue({ first: '1', second: '2' }))
    return (
      <EnvironmentMapEditor value={value} onChange={setValue} kind="variables" readOnly={false} />
    )
  }
  render(<Editor />)
  fireEvent.change(screen.getByLabelText('变量名称 2'), { target: { value: 'first' } })
  await userEvent.click(screen.getByRole('button', { name: '变量高级 JSON' }))
  expect(screen.getByText('变量名称不能重复：first')).toBeVisible()
  fireEvent.change(screen.getByLabelText('变量名称 2'), { target: { value: 'second' } })
  expect(screen.queryByText('变量名称不能重复：first')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '变量高级 JSON' }))
  const field = screen.getByRole('textbox', { name: '变量 JSON' }) as HTMLTextAreaElement
  expect(JSON.parse(field.value)).toEqual({ first: '1', second: '2' })
})
