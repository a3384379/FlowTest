import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useEffect } from 'react'
import ApiWorkspace from './ApiWorkspace'
import { apiWorkspaceKey } from './api-layout-preferences'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})
const key = 'api-layout-test'
function workspace(request = <input aria-label="请求草稿" defaultValue="原始路径" />) {
  return (
    <ApiWorkspace
      preferenceKey={key}
      directory={<p>目录内容</p>}
      request={request}
      response={<p>已获取响应</p>}
    />
  )
}

describe('API workspace layout', () => {
  it('adjusts both separators by keyboard and restores the project preference after reopening', async () => {
    const view = render(workspace())
    fireEvent.keyDown(screen.getByRole('separator', { name: '调整接口目录宽度' }), {
      key: 'ArrowRight',
    })
    fireEvent.keyDown(screen.getByRole('separator', { name: '调整请求响应比例' }), {
      key: 'ArrowLeft',
    })
    expect(screen.getByRole('separator', { name: '调整接口目录宽度' })).toHaveAttribute(
      'aria-valuenow',
      '256',
    )
    expect(screen.getByRole('separator', { name: '调整请求响应比例' })).toHaveAttribute(
      'aria-valuenow',
      '50',
    )
    await userEvent.click(screen.getByText('上下分栏'))
    fireEvent.keyDown(screen.getByRole('separator', { name: '调整请求响应比例' }), {
      key: 'ArrowDown',
    })
    expect(screen.getByRole('separator', { name: '调整请求响应比例' })).toHaveAttribute(
      'aria-orientation',
      'horizontal',
    )
    view.unmount()
    render(workspace())
    expect(screen.getByRole('separator', { name: '调整接口目录宽度' })).toHaveAttribute(
      'aria-valuenow',
      '256',
    )
    expect(screen.getByRole('separator', { name: '调整请求响应比例' })).toHaveAttribute(
      'aria-valuenow',
      '52',
    )
    expect(screen.getByRole('separator', { name: '调整请求响应比例' })).toHaveAttribute(
      'aria-orientation',
      'horizontal',
    )
  })
  it('preserves request fields and response children across layout and collapsed states', async () => {
    const mounted = vi.fn()
    function Request() {
      useEffect(() => {
        mounted()
      }, [])
      return <input aria-label="请求草稿" defaultValue="原始路径" />
    }
    render(workspace(<Request />))
    await userEvent.type(screen.getByRole('textbox', { name: '请求草稿' }), '修改')
    await userEvent.click(screen.getByText('上下分栏'))
    await userEvent.click(screen.getByRole('button', { name: '收起目录' }))
    await userEvent.click(screen.getByRole('button', { name: '收起响应' }))
    await userEvent.click(screen.getByRole('button', { name: '展开响应' }))
    expect(screen.getByRole('textbox', { name: '请求草稿' })).toHaveValue('原始路径修改')
    expect(screen.getByText('已获取响应')).toBeInTheDocument()
    expect(mounted).toHaveBeenCalledTimes(1)
  })
  it('bounds invalid stored dimensions and lets users keep working if storage is unavailable', async () => {
    localStorage.setItem(
      key,
      JSON.stringify({ directoryWidth: 10000, requestShare: -20, layout: 'unknown' }),
    )
    render(workspace())
    expect(screen.getByRole('separator', { name: '调整接口目录宽度' })).toHaveAttribute(
      'aria-valuenow',
      '340',
    )
    expect(screen.getByRole('separator', { name: '调整请求响应比例' })).toHaveAttribute(
      'aria-valuenow',
      '30',
    )
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    await userEvent.click(screen.getByRole('button', { name: '收起目录' }))
    expect(screen.getByRole('button', { name: '展开目录' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.getByRole('status')).toHaveTextContent('布局偏好未保存')
    await userEvent.type(screen.getByRole('textbox', { name: '请求草稿' }), '继续编辑')
    expect(screen.getByRole('textbox', { name: '请求草稿' })).toHaveValue('原始路径继续编辑')
  })
  it('falls back from corrupt storage and separates users and projects', () => {
    localStorage.setItem(key, 'broken')
    render(workspace())
    expect(screen.getByRole('separator', { name: '调整接口目录宽度' })).toHaveAttribute(
      'aria-valuenow',
      '240',
    )
    expect(apiWorkspaceKey('user-a', 'project-a')).not.toBe(apiWorkspaceKey('user-b', 'project-a'))
    expect(apiWorkspaceKey('user-a', 'project-a')).not.toBe(apiWorkspaceKey('user-a', 'project-b'))
  })
})
