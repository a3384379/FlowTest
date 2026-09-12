import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkflowDefinition } from '../../lib/api'
import {
  readWorkflowDraft,
  removeWorkflowDraft,
  workflowDraftKey,
  writeWorkflowDraft,
} from './workflow-draft-store'
import { readWorkflowTabs, workflowTabKey, writeWorkflowTabs } from './workflow-tab-store'
import { useWorkflowTabs } from './use-workflow-tabs'

const draft = { nodes: [], edges: [] } as unknown as WorkflowDefinition

describe('useWorkflowTabs', () => {
  it('ignores close resolution when no close request is pending', async () => {
    const rendered = renderTabsHook()
    await act(async () => rendered.result.current.resolvePendingClose('discard'))
    expect(rendered.result.current.pendingClose).toBeNull()
  })

  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('restores a scoped tab record and updates focus when activating a tab', async () => {
    const key = workflowTabKey('user-1', 'project-1')
    writeWorkflowTabs(key, ['one', 'two'], 'two')
    const selectWorkflow = vi.fn()
    const setSearchParams = vi.fn()
    const searchParams = new URLSearchParams('focus=one')
    const rendered = renderHook(
      ({ activeWorkflowId }: { activeWorkflowId: string | null }) =>
        useWorkflowTabs({
          userId: 'user-1',
          projectId: 'project-1',
          workflowIds: ['one', 'two'],
          activeWorkflowId,
          hasExplicitFocus: false,
          selectWorkflow,
          saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
          searchParams,
          setSearchParams,
        }),
      { initialProps: { activeWorkflowId: null as string | null } },
    )

    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['one', 'two']))
    await waitFor(() => expect(selectWorkflow).toHaveBeenCalledWith('two'))

    act(() => rendered.result.current.activateWorkflow('one'))
    expect(selectWorkflow).toHaveBeenLastCalledWith('one')
    expect(setSearchParams).toHaveBeenLastCalledWith(
      expect.objectContaining({ get: expect.any(Function) }),
      { replace: true },
    )
    const focused = setSearchParams.mock.calls.at(-1)?.[0] as URLSearchParams
    expect(focused.get('focus')).toBe('one')

    rendered.rerender({ activeWorkflowId: 'one' })
    await waitFor(() => expect(readWorkflowTabs(key)?.activeWorkflowId).toBe('one'))
  })

  it('closes clean tabs and selects the next tab or clears focus', async () => {
    const key = workflowTabKey('user-1', 'project-1')
    writeWorkflowTabs(key, ['one', 'two'], 'one')
    const selectWorkflow = vi.fn()
    const setSearchParams = vi.fn()
    const rendered = renderHook(
      ({ activeWorkflowId }: { activeWorkflowId: string | null }) =>
        useWorkflowTabs({
          userId: 'user-1',
          projectId: 'project-1',
          workflowIds: ['one', 'two'],
          activeWorkflowId,
          hasExplicitFocus: true,
          selectWorkflow,
          saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
          searchParams: new URLSearchParams('focus=one'),
          setSearchParams,
        }),
      { initialProps: { activeWorkflowId: 'one' as string | null } },
    )

    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['one', 'two']))
    act(() => rendered.result.current.requestCloseTabs(['missing']))
    expect(rendered.result.current.workflowIds).toEqual(['one', 'two'])

    act(() => rendered.result.current.requestCloseTabs(['one']))
    rendered.rerender({ activeWorkflowId: 'two' })
    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['two']))
    expect(selectWorkflow).toHaveBeenLastCalledWith('two')

    act(() => rendered.result.current.requestCloseTabs(['one', 'two']))
    rendered.rerender({ activeWorkflowId: null })
    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual([]))
    expect(selectWorkflow).toHaveBeenLastCalledWith(null)
    const cleared = setSearchParams.mock.calls.at(-1)?.[0] as URLSearchParams
    expect(cleared.has('focus')).toBe(false)
  })

  it('requires a decision for dirty tabs and can discard their local draft', async () => {
    writeWorkflowTabs(workflowTabKey('user-1', 'project-1'), ['one'], 'one')
    const draftKey = workflowDraftKey('user-1', 'project-1', 'one')
    writeWorkflowDraft(draftKey, draft, 1, 1)
    const rendered = renderTabsHook(undefined, null)

    await waitFor(() => expect(rendered.result.current.dirtyIds).toEqual(['one']))
    act(() => rendered.result.current.requestCloseTabs(['one']))
    expect(rendered.result.current.pendingClose).toEqual({ ids: ['one'], dirtyIds: ['one'] })
    act(() => rendered.result.current.cancelPendingClose())
    expect(rendered.result.current.pendingClose).toBeNull()
    act(() => rendered.result.current.requestCloseTabs(['one']))

    await act(async () => {
      await rendered.result.current.resolvePendingClose('discard')
    })
    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual([]))
    expect(rendered.result.current.pendingClose).toBeNull()
    expect(readWorkflowDraft(draftKey)).toBeNull()
  })

  it('refreshes dirty markers when a draft changes after tabs load', async () => {
    const tabsKey = workflowTabKey('user-1', 'project-1')
    const draftKey = workflowDraftKey('user-1', 'project-1', 'one')
    writeWorkflowTabs(tabsKey, ['one'], 'one')
    const rendered = renderTabsHook()

    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['one']))
    expect(rendered.result.current.dirtyIds).toEqual([])

    act(() => writeWorkflowDraft(draftKey, draft, 1, 1))
    await waitFor(() => expect(rendered.result.current.dirtyIds).toEqual(['one']))

    act(() => removeWorkflowDraft(draftKey))
    await waitFor(() => expect(rendered.result.current.dirtyIds).toEqual([]))
  })

  it('saves dirty tabs before closing and keeps the dialog open on save failure', async () => {
    writeWorkflowTabs(workflowTabKey('user-1', 'project-1'), ['one'], 'one')
    writeWorkflowDraft(workflowDraftKey('user-1', 'project-1', 'one'), draft, 1, 1)
    const saveWorkflowDraft = vi.fn().mockResolvedValue(undefined)
    const rendered = renderTabsHook(saveWorkflowDraft, null)

    await waitFor(() => expect(rendered.result.current.dirtyIds).toEqual(['one']))
    act(() => rendered.result.current.requestCloseTabs(['one']))
    await act(async () => {
      await rendered.result.current.resolvePendingClose('save')
    })
    expect(saveWorkflowDraft).toHaveBeenCalledWith('one')
    await waitFor(() => expect(rendered.result.current.pendingClose).toBeNull())

    writeWorkflowDraft(workflowDraftKey('user-1', 'project-1', 'one'), draft, 1, 1)
    writeWorkflowTabs(workflowTabKey('user-1', 'project-1'), ['one'], 'one')
    const failingSave = vi.fn().mockRejectedValue(new Error('conflict'))
    const failed = renderTabsHook(failingSave, null)
    await waitFor(() => expect(failed.result.current.dirtyIds).toEqual(['one']))
    act(() => failed.result.current.requestCloseTabs(['one']))
    await act(async () => {
      await failed.result.current.resolvePendingClose('save')
    })
    expect(failed.result.current.pendingClose).toEqual({ ids: ['one'], dirtyIds: ['one'] })
    expect(failed.result.current.closingTabs).toBe(false)
  })

  it('keeps the discard confirmation open when local draft cleanup fails', async () => {
    writeWorkflowTabs(workflowTabKey('user-1', 'project-1'), ['one'], 'one')
    writeWorkflowDraft(workflowDraftKey('user-1', 'project-1', 'one'), draft, 1, 1)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    const rendered = renderTabsHook(undefined, null)

    await waitFor(() => expect(rendered.result.current.dirtyIds).toEqual(['one']))
    act(() => rendered.result.current.requestCloseTabs(['one']))
    await act(async () => {
      await rendered.result.current.resolvePendingClose('discard')
    })
    expect(rendered.result.current.pendingClose).toEqual({ ids: ['one'], dirtyIds: ['one'] })
    expect(rendered.result.current.storageError).toBe('本地草稿清理失败')
    expect(rendered.result.current.closingTabs).toBe(false)
  })

  it('uses the workflow draft lifecycle to discard an in-memory draft', async () => {
    const discardWorkflowDraft = vi.fn(() => ({ ok: true }) as const)
    const rendered = renderHook(() =>
      useWorkflowTabs({
        userId: 'user-1',
        projectId: 'project-1',
        workflowIds: ['one'],
        activeWorkflowId: 'one',
        hasExplicitFocus: true,
        selectWorkflow: vi.fn(),
        saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
        discardWorkflowDraft,
        memoryDraftIds: ['one'],
        searchParams: new URLSearchParams('focus=one'),
        setSearchParams: vi.fn(),
      }),
    )

    await waitFor(() => expect(rendered.result.current.dirtyIds).toEqual(['one']))
    act(() => rendered.result.current.requestCloseTabs(['one']))
    await act(async () => rendered.result.current.resolvePendingClose('discard'))
    expect(discardWorkflowDraft).toHaveBeenCalledWith('one')
  })

  it('keeps the close request open when the workflow lifecycle cannot discard', async () => {
    const discardWorkflowDraft = vi.fn(() => ({ ok: false, error: '内存草稿仍被保留' }) as const)
    const rendered = renderHook(() =>
      useWorkflowTabs({
        userId: 'user-1',
        projectId: 'project-1',
        workflowIds: ['one'],
        activeWorkflowId: 'one',
        hasExplicitFocus: true,
        selectWorkflow: vi.fn(),
        saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
        discardWorkflowDraft,
        memoryDraftIds: ['one'],
        searchParams: new URLSearchParams('focus=one'),
        setSearchParams: vi.fn(),
      }),
    )

    await waitFor(() => expect(rendered.result.current.dirtyIds).toEqual(['one']))
    act(() => rendered.result.current.requestCloseTabs(['one']))
    await act(async () => rendered.result.current.resolvePendingClose('discard'))
    expect(rendered.result.current.storageError).toBe('内存草稿仍被保留')
    expect(rendered.result.current.pendingClose).not.toBeNull()
  })

  it('can discard an in-memory draft without browser identity', async () => {
    const rendered = renderHook(() =>
      useWorkflowTabs({
        userId: undefined,
        projectId: null,
        workflowIds: ['one'],
        activeWorkflowId: 'one',
        hasExplicitFocus: true,
        selectWorkflow: vi.fn(),
        saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
        memoryDraftIds: ['one'],
        searchParams: new URLSearchParams('focus=one'),
        setSearchParams: vi.fn(),
      }),
    )
    act(() => rendered.result.current.requestCloseTabs(['one']))
    await act(async () => rendered.result.current.resolvePendingClose('discard'))
    expect(rendered.result.current.pendingClose).toBeNull()
  })

  it('surfaces tab storage errors while retaining the in-memory tabs', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    const rendered = renderTabsHook()

    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['one']))
    await waitFor(() =>
      expect(rendered.result.current.storageError).toBe(
        '工作区页签保存失败，当前页签仍保留在内存中',
      ),
    )
  })

  it('resets state when the user or project scope is unavailable', async () => {
    const rendered = renderHook(() =>
      useWorkflowTabs({
        userId: undefined,
        projectId: null,
        workflowIds: ['one'],
        activeWorkflowId: 'one',
        hasExplicitFocus: true,
        selectWorkflow: vi.fn(),
        saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
        searchParams: new URLSearchParams(),
        setSearchParams: vi.fn(),
      }),
    )

    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual([]))
    expect(rendered.result.current.storageError).toBeNull()
  })

  it('clears the previous user tab record when logging out', async () => {
    const key = workflowTabKey('user-1', 'project-1')
    writeWorkflowTabs(key, ['one'], 'one')
    const rendered = renderHook(
      ({ userId }: { userId: string | undefined }) =>
        useWorkflowTabs({
          userId,
          projectId: 'project-1',
          workflowIds: ['one'],
          activeWorkflowId: 'one',
          hasExplicitFocus: true,
          selectWorkflow: vi.fn(),
          saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
          searchParams: new URLSearchParams('focus=one'),
          setSearchParams: vi.fn(),
        }),
      { initialProps: { userId: 'user-1' as string | undefined } },
    )

    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['one']))
    rendered.rerender({ userId: undefined })
    await waitFor(() => expect(readWorkflowTabs(key)).toBeNull())
  })

  it('clears tabs from the previous user without deleting another project for the same user', async () => {
    const firstUserKey = workflowTabKey('user-1', 'project-1')
    const sameUserProjectKey = workflowTabKey('user-1', 'project-2')
    writeWorkflowTabs(firstUserKey, ['one'], 'one')
    writeWorkflowTabs(sameUserProjectKey, ['two'], 'two')
    const rendered = renderHook(
      ({ userId, projectId }: { userId: string; projectId: string }) =>
        useWorkflowTabs({
          userId,
          projectId,
          workflowIds: ['one', 'two'],
          activeWorkflowId: null,
          hasExplicitFocus: true,
          selectWorkflow: vi.fn(),
          saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
          searchParams: new URLSearchParams(),
          setSearchParams: vi.fn(),
        }),
      { initialProps: { userId: 'user-1', projectId: 'project-1' } },
    )

    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['one']))
    rendered.rerender({ userId: 'user-1', projectId: 'project-2' })
    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['two']))
    expect(readWorkflowTabs(firstUserKey)).not.toBeNull()

    rendered.rerender({ userId: 'user-2', projectId: 'project-1' })
    await waitFor(() => expect(readWorkflowTabs(sameUserProjectKey)).toBeNull())
  })

  it('reports a previous-user tab cleanup failure during an identity switch', async () => {
    writeWorkflowTabs(workflowTabKey('user-1', 'project-1'), ['one'], 'one')
    const rendered = renderHook(
      ({ userId }: { userId: string }) =>
        useWorkflowTabs({
          userId,
          projectId: 'project-1',
          workflowIds: ['one'],
          activeWorkflowId: 'one',
          hasExplicitFocus: true,
          selectWorkflow: vi.fn(),
          saveWorkflowDraft: vi.fn().mockResolvedValue(undefined),
          searchParams: new URLSearchParams('focus=one'),
          setSearchParams: vi.fn(),
        }),
      { initialProps: { userId: 'user-1' } },
    )
    await waitFor(() => expect(rendered.result.current.workflowIds).toEqual(['one']))
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })

    rendered.rerender({ userId: 'user-2' })

    await waitFor(() => expect(rendered.result.current.storageError).toBe('工作区页签清理失败'))
  })
})

function renderTabsHook(
  saveWorkflowDraft: (workflowId: string) => Promise<void> = vi.fn().mockResolvedValue(undefined),
  activeWorkflowId: string | null = 'one',
) {
  return renderHook(() =>
    useWorkflowTabs({
      userId: 'user-1',
      projectId: 'project-1',
      workflowIds: ['one'],
      activeWorkflowId,
      hasExplicitFocus: true,
      selectWorkflow: vi.fn(),
      saveWorkflowDraft,
      searchParams: new URLSearchParams('focus=one'),
      setSearchParams: vi.fn(),
    }),
  )
}
