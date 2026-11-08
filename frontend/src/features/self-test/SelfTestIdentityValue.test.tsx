import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import SelfTestIdentityValue from './SelfTestIdentityValue'

describe('registered self-test identity values', () => {
  it('keeps full evidence selectable when clipboard access fails', async () => {
    const browser = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('denied'))
    const value = 'sha256:' + 'abcdef0123456789'.repeat(4)
    render(<SelfTestIdentityValue label="构建" value={value} />)
    expect(screen.getByText(value)).not.toBeVisible()
    await browser.click(screen.getByRole('button', { name: '复制完整构建' }))
    expect(await screen.findByRole('status')).toHaveTextContent('复制失败')
    await browser.click(screen.getByText('显示完整值'))
    expect(screen.getByText(value)).toBeVisible()
  })
  it('does not apply a late copy receipt to a different selected identity', async () => {
    const browser = userEvent.setup()
    let resolve!: () => void
    const copied = vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(
      () =>
        new Promise<void>((done) => {
          resolve = done
        }),
    )
    const view = render(<SelfTestIdentityValue label="Runner" value="old-runner" />)
    await browser.click(screen.getByRole('button', { name: '复制完整Runner' }))
    view.rerender(<SelfTestIdentityValue label="Runner" value="new-runner" />)
    await act(async () => resolve())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    copied.mockResolvedValue()
    await browser.click(screen.getByRole('button', { name: '复制完整Runner' }))
    expect(copied).toHaveBeenLastCalledWith('new-runner')
    expect(await screen.findByRole('status')).toHaveTextContent('已复制完整值')
    expect(screen.queryByText('显示完整值')).not.toBeInTheDocument()
  })
})
