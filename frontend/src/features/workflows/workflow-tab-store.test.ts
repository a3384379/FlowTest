import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  readWorkflowTabs,
  removeWorkflowTabs,
  workflowTabKey,
  writeWorkflowTabs,
} from './workflow-tab-store'

describe('workflow tab store', () => {
  afterEach(() => {
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('round trips an isolated tab order and active tab', () => {
    const key = workflowTabKey('user/1', 'project/1', 'https://flowtest.example')
    expect(writeWorkflowTabs(key, ['one', 'two', 'one'], 'two')).toEqual({ ok: true })
    expect(readWorkflowTabs(key)).toEqual({
      schemaVersion: 1,
      resourceKey: key,
      workflowIds: ['one', 'two'],
      activeWorkflowId: 'two',
    })
    expect(removeWorkflowTabs(key)).toEqual({ ok: true })
    expect(readWorkflowTabs(key)).toBeNull()
  })

  it('does not reuse another user or project tab record', () => {
    const first = workflowTabKey('first', 'project', 'server')
    const second = workflowTabKey('second', 'project', 'server')
    writeWorkflowTabs(first, ['workflow'], 'workflow')
    expect(readWorkflowTabs(second)).toBeNull()
  })

  it('drops malformed records and reports storage failures', () => {
    const key = workflowTabKey('user', 'project', 'server')
    const prefix = 'flowtest:workflow-tabs:v1:'
    sessionStorage.setItem(`${prefix}server:user:bad`, JSON.stringify({ schemaVersion: 1 }))
    expect(readWorkflowTabs({ ...key, projectId: 'bad' })).toBeNull()
    sessionStorage.setItem(`${prefix}server:user:json`, '{')
    expect(readWorkflowTabs({ ...key, projectId: 'json' })).toBeNull()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(writeWorkflowTabs(key, ['workflow'], 'workflow')).toEqual({
      ok: false,
      error: '工作区页签保存失败，当前页签仍保留在内存中',
    })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(removeWorkflowTabs(key)).toEqual({ ok: false, error: '工作区页签清理失败' })
  })

  it('returns a clear error when session storage is unavailable', () => {
    const key = workflowTabKey('user', 'project', 'server')
    const getter = vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    expect(readWorkflowTabs(key)).toBeNull()
    expect(writeWorkflowTabs(key, ['workflow'], 'workflow')).toEqual({
      ok: false,
      error: '当前浏览器不支持工作区页签保存',
    })
    expect(removeWorkflowTabs(key)).toEqual({
      ok: false,
      error: '当前浏览器不支持工作区页签保存',
    })
    getter.mockRestore()
  })
})
