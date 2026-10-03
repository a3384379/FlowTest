import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ResponseCodeReader from './ResponseCodeReader'

describe('response code reader', () => {
  it('formats, highlights, and wraps the captured JSON without changing its value', async () => {
    const value = { id: 42, name: '<script>danger</script>', active: true }
    const browser = userEvent.setup()
    const copied = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const { container } = render(<ResponseCodeReader value={value} title="响应内容" />)
    expect(container.querySelector('.response-token-key')).toHaveTextContent('"id"')
    expect(container.querySelector('script')).toBeNull()
    await browser.click(screen.getByRole('switch', { name: '响应内容格式化' }))
    expect(container.querySelector('.response-reader-text')?.textContent).toBe(
      JSON.stringify(value),
    )
    await browser.click(screen.getByRole('switch', { name: '响应内容自动换行' }))
    expect(container.querySelector('.response-reader-code')).toHaveClass('is-wrapped')
    await browser.click(screen.getByRole('button', { name: '复制完整内容' }))
    expect(copied).toHaveBeenCalledWith(JSON.stringify(value))
    expect(screen.getByRole('status')).toHaveTextContent('已复制完整内容')
  })

  it('bounds the preview and copies the full captured content', async () => {
    const browser = userEvent.setup()
    const copied = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const text = Array.from({ length: 600 }, (_, index) => `line-${index}`).join('\n')
    const { container } = render(<ResponseCodeReader value={text} title="响应内容" />)
    expect(screen.getByText(/仅预览前 300 行/)).toBeVisible()
    expect(container.querySelector('.response-reader-text')?.textContent?.split('\n')).toHaveLength(
      300,
    )
    await browser.click(screen.getByRole('button', { name: '复制完整内容' }))
    expect(copied).toHaveBeenCalledWith(text)
  })

  it('keeps copy failures visible without dropping the captured content', async () => {
    userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('unavailable'))
    render(<ResponseCodeReader value="source response" title="响应内容" />)
    fireEvent.click(screen.getByRole('button', { name: '复制完整内容' }))
    expect(await screen.findByRole('status')).toHaveTextContent('复制失败')
    expect(screen.getByText('source response')).toBeVisible()
  })
})
