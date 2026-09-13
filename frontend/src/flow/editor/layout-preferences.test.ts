import { afterEach, expect, it, vi } from 'vitest'
import {
  readLayoutPreferences,
  workflowLayoutKey,
  writeLayoutPreferences,
} from './layout-preferences'
afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})
it('separates server/user/project preferences and sanitizes malformed dimensions', () => {
  const key = workflowLayoutKey('user-a', 'project-a')
  expect(key).not.toBe(workflowLayoutKey('user-b', 'project-a'))
  expect(key).not.toBe(workflowLayoutKey('user-a', 'project-b'))
  expect(workflowLayoutKey()).toContain('anonymous:embedded')
  localStorage.setItem(
    key,
    JSON.stringify({
      inspectorWidth: 9999,
      listWidth: 2,
      requestWidth: 'wrong',
      listCollapsed: true,
      unrelated: 'ignored',
    }),
  )
  expect(readLayoutPreferences(key)).toEqual({
    inspectorWidth: 640,
    listWidth: 180,
    requestWidth: 760,
    listCollapsed: true,
  })
  expect(writeLayoutPreferences(key, { requestWidth: 900 })).toBe(true)
  expect(JSON.parse(localStorage.getItem(key)!)).toEqual({
    inspectorWidth: 640,
    listWidth: 180,
    requestWidth: 900,
    listCollapsed: true,
  })
  for (const raw of ['{', 'null', '[]', '3']) {
    localStorage.setItem(key, raw)
    expect(readLayoutPreferences(key).inspectorWidth).toBe(400)
  }
})
it('reports write failure without throwing or clearing draft storage', () => {
  localStorage.setItem('draft', 'retain')
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('quota')
  })
  expect(writeLayoutPreferences('layout', { listCollapsed: false })).toBe(false)
  expect(localStorage.getItem('draft')).toBe('retain')
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('disabled')
  })
  expect(readLayoutPreferences('layout').listWidth).toBe(256)
})

it('uses the accepted default workflow list width', () => {
  expect(readLayoutPreferences('new-layout').listWidth).toBe(256)
})
