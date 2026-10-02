import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import AppearanceSettings from './AppearanceSettings'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

it('stores appearance separately per user while preserving earlier themes, navigation and drafts', async () => {
  localStorage.setItem('flowtest:theme', 'dark')
  localStorage.setItem('draft', 'retain')
  const browser = userEvent.setup()
  const view = render(<AppearanceSettings userId="alice" />)
  await browser.click(screen.getByRole('button', { name: '外观设置' }))
  await browser.click(screen.getByRole('switch', { name: '减少透明效果' }))
  expect(document.documentElement.dataset.reduceTransparency).toBe('true')
  expect(JSON.parse(localStorage.getItem('flowtest:appearance:v5:alice')!)).toEqual({
    reduceTransparency: true,
  })
  view.unmount()
  render(<AppearanceSettings userId="bob" />)
  expect(document.documentElement.dataset.reduceTransparency).toBe('false')
  expect(localStorage.getItem('flowtest:theme')).toBe('dark')
  expect(localStorage.getItem('draft')).toBe('retain')
})

it('applies the current appearance when preference persistence fails', async () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('quota')
  })
  const browser = userEvent.setup()
  render(<AppearanceSettings userId="alice" />)
  await browser.click(screen.getByRole('button', { name: '外观设置' }))
  await browser.click(screen.getByRole('switch', { name: '减少透明效果' }))
  expect(document.documentElement.dataset.reduceTransparency).toBe('true')
})
