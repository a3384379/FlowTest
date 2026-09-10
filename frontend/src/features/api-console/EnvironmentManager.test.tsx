import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App as AntdApp } from 'antd'
import { describe, expect, it, vi } from 'vitest'

import { environment } from '../../test/fixtures'
import type { CreateEnvironmentInput } from './api-service'
import EnvironmentManager from './EnvironmentManager'

type SaveHandler = (input: Partial<CreateEnvironmentInput>) => Promise<void>
type DeleteHandler = () => Promise<void>

describe('EnvironmentManager', () => {
  it('loads an environment, saves typed maps, and opens deletion confirmation', async () => {
    const onSave = vi.fn<SaveHandler>().mockResolvedValue(undefined)
    const onDelete = vi.fn<DeleteHandler>().mockResolvedValue(undefined)
    renderManager({ onSave, onDelete })
    const browser = userEvent.setup()

    expect(await screen.findByDisplayValue(environment.base_url)).toBeVisible()
    await browser.clear(screen.getByLabelText('变量 JSON'))
    fireEvent.change(screen.getByLabelText('变量 JSON'), { target: { value: '{"region":"cn"}' } })
    await browser.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        name: environment.name,
        base_url: environment.base_url,
        variables: { region: 'cn' },
        headers: environment.headers,
      }),
    )

    await browser.click(screen.getByRole('button', { name: /删除$/ }))
    expect(await screen.findByRole('tooltip')).toHaveTextContent('删除环境？')
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('keeps the form and reports invalid JSON without saving', async () => {
    const onSave = vi.fn<SaveHandler>().mockResolvedValue(undefined)
    renderManager({ onSave })
    const browser = userEvent.setup()
    const variables = screen.getByLabelText('变量 JSON')
    await browser.clear(variables)
    fireEvent.change(variables, { target: { value: '[]' } })
    await browser.click(screen.getByRole('button', { name: /保存配置/ }))
    await waitFor(() => expect(onSave).not.toHaveBeenCalled())
    expect(screen.getByLabelText('变量 JSON')).toHaveClass('ant-input-status-error')
  })

  it('explains that a manager needs a selected environment', () => {
    const onSave = vi.fn<SaveHandler>().mockResolvedValue(undefined)
    const onDelete = vi.fn<DeleteHandler>().mockResolvedValue(undefined)
    render(
      <AntdApp>
        <EnvironmentManager
          open
          saving={false}
          deleting={false}
          onClose={vi.fn()}
          onSave={onSave}
          onDelete={onDelete}
        />
      </AntdApp>,
    )
    expect(screen.getByText('请选择环境后管理其配置。')).toBeVisible()
  })
})

function renderManager(overrides: { onSave: SaveHandler; onDelete?: DeleteHandler }) {
  return render(
    <AntdApp>
      <EnvironmentManager
        open
        environment={environment}
        saving={false}
        deleting={false}
        onClose={vi.fn()}
        onSave={overrides.onSave}
        onDelete={overrides.onDelete ?? vi.fn<DeleteHandler>().mockResolvedValue(undefined)}
      />
    </AntdApp>,
  )
}
