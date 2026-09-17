import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { readNavigationPreference, writeNavigationPreference } from './navigation-preferences'

describe('navigation preferences', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('isolates users and ignores unknown keys and invalid values', () => {
    localStorage.setItem(
      'flowtest:navigation:v1:alice',
      JSON.stringify({
        collapsed: true,
        openKeys: ['apis', 'unknown', 'nav:test-design', 'nav:quality'],
      }),
    )
    expect(readNavigationPreference('alice')).toEqual({
      collapsed: true,
      openKeys: ['nav:quality'],
    })
    expect(readNavigationPreference('bob')).toEqual({ collapsed: null, openKeys: [] })
    localStorage.setItem(
      'flowtest:navigation:v1:bob',
      JSON.stringify({ collapsed: 'yes', openKeys: false }),
    )
    expect(readNavigationPreference('bob')).toEqual({ collapsed: null, openKeys: [] })
  })

  it.each(['{', 'null', '[]', 'false'])('recovers from invalid stored data %s', (value) => {
    localStorage.setItem('flowtest:navigation:v1:alice', value)
    expect(readNavigationPreference('alice')).toEqual({ collapsed: null, openKeys: [] })
  })

  it('supports browsers where storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('Unavailable')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Unavailable')
    })
    expect(readNavigationPreference('alice')).toEqual({ collapsed: null, openKeys: [] })
    expect(() =>
      writeNavigationPreference('alice', { collapsed: true, openKeys: [] }),
    ).not.toThrow()
  })
})
