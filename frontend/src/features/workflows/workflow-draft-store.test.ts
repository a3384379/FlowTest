import { afterEach, describe, expect, it, vi } from 'vitest'

import type { WorkflowDefinition } from '../../lib/api'
import {
  clearWorkflowDrafts,
  readWorkflowDraft,
  removeWorkflowDraft,
  workflowDraftKey,
  writeWorkflowDraft,
} from './workflow-draft-store'

const content = { nodes: [], edges: [] } as unknown as WorkflowDefinition

describe('workflow draft store', () => {
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('round trips a resource-scoped draft and removes it', () => {
    const key = workflowDraftKey('user/1', 'project', 'workflow')
    expect(writeWorkflowDraft(key, content, 3, 4)).toEqual({ ok: true })
    expect(readWorkflowDraft(key)).toMatchObject({
      schemaVersion: 1,
      resourceKey: key,
      baseRevision: 3,
      editVersion: 4,
      content,
    })
    expect(removeWorkflowDraft(key)).toEqual({ ok: true })
    expect(readWorkflowDraft(key)).toBeNull()
  })

  it('drops malformed records and clears only the requested user drafts', () => {
    const first = workflowDraftKey('first', 'project', 'one')
    const second = workflowDraftKey('second', 'project', 'two')
    writeWorkflowDraft(first, content, 1, 1)
    writeWorkflowDraft(second, content, 1, 1)
    const malformedKey = `flowtest:workflow-draft:v1:${encodeURIComponent(first.serverInstance)}:first:project:other`
    localStorage.setItem(malformedKey, JSON.stringify({ schemaVersion: 1, content: {} }))
    expect(readWorkflowDraft({ ...first, workflowId: 'other' })).toBeNull()
    expect(clearWorkflowDrafts('first')).toEqual({ ok: true })
    expect(readWorkflowDraft(first)).toBeNull()
    expect(readWorkflowDraft(second)).not.toBeNull()
    expect(localStorage.getItem(malformedKey)).toBeNull()
  })

  it('reports unavailable storage and malformed JSON without throwing', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => '{')
    const key = workflowDraftKey('user', 'project', 'workflow')
    expect(readWorkflowDraft(key)).toBeNull()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(writeWorkflowDraft(key, content, 1, 1)).toEqual({
      ok: false,
      error: '本地保存失败，已保留当前内存编辑内容',
    })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(removeWorkflowDraft(key)).toEqual({ ok: false, error: '本地草稿清理失败' })
  })

  it('returns a clear error when local storage is unavailable', () => {
    const key = workflowDraftKey('user', 'project', 'workflow')
    const getter = vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    expect(readWorkflowDraft(key)).toBeNull()
    expect(writeWorkflowDraft(key, content, 1, 1)).toEqual({
      ok: false,
      error: '当前浏览器不支持本地草稿保存',
    })
    expect(removeWorkflowDraft(key)).toEqual({
      ok: false,
      error: '当前浏览器不支持本地草稿保存',
    })
    expect(clearWorkflowDrafts('user')).toEqual({
      ok: false,
      error: '当前浏览器不支持本地草稿保存',
    })
    getter.mockRestore()
  })
})
