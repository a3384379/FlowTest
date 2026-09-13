import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { BulkDraftContext, useBulkDraft } from './use-bulk-draft'
it('restores unfinished bulk input and keeps same-turn updates and errors together', () => {
  const onChange = vi.fn()
  const drafts = { params: { text: 'unfinished', errors: ['缺少分隔符'] } }
  const { result, unmount } = renderHook(() => useBulkDraft('params'), {
    wrapper: ({ children }) => (
      <BulkDraftContext.Provider value={{ drafts, onChange }}>{children}</BulkDraftContext.Provider>
    ),
  })
  expect(result.current.bulkText).toBe('unfinished')
  expect(result.current.bulkErrors).toEqual(['缺少分隔符'])
  act(() => {
    result.current.setBulkText('name: value')
    result.current.setBulkErrors([])
  })
  expect(onChange).toHaveBeenLastCalledWith('params', { text: 'name: value', errors: [] })
  unmount()
  const restored = renderHook(() => useBulkDraft('params'), {
    wrapper: ({ children }) => (
      <BulkDraftContext.Provider
        value={{ drafts: { params: { text: 'name: value', errors: [] } }, onChange }}
      >
        {children}
      </BulkDraftContext.Provider>
    ),
  })
  expect(restored.result.current.bulkText).toBe('name: value')
  act(() => restored.result.current.setBulkText(null))
  expect(onChange).toHaveBeenLastCalledWith('params', { text: null, errors: [] })
})
