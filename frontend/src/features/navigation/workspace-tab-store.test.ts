import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  readWorkspaceTabs,
  routeWorkspaceTab,
  writeWorkspaceTabs,
  workspaceTabStorageKey,
} from './workspace-tab-store'

beforeEach(() => localStorage.clear())

describe('scoped object workspace tab storage', () => {
  it('keeps object identities distinct and the complete execution context through reload', () => {
    const one = routeWorkspaceTab(
      'p',
      '/projects/p/workflows?focus=flow-A&execution=run-A&node=loop&attempt=2&control_kind=iteration&control_ordinal=3&instance=__nested_request__%3Achild&instance_attempt=1#trace',
    )!
    const two = routeWorkspaceTab('p', '/projects/p/workflows?focus=flow-B')!
    const api = routeWorkspaceTab('p', '/projects/p/apis?focus=api-A&execution=api-run')!
    const report = routeWorkspaceTab(
      'p',
      '/projects/p/reports?execution=run-A&node=loop&control_ordinal=3',
    )!
    expect(new Set([one.key, two.key, api.key, report.key]).size).toBe(4)
    expect(writeWorkspaceTabs('user-A', 'p', [one, two, api, report])).toBeNull()
    expect(readWorkspaceTabs('user-A', 'p').tabs).toEqual([one, two, api, report])
    expect(readWorkspaceTabs('user-B', 'p').tabs).toEqual([])
    expect(readWorkspaceTabs('user-A', 'other-project').tabs).toEqual([])
  })

  it('rejects external and foreign project navigation and migrates only valid module tabs', () => {
    for (const href of [
      'https://example.com',
      '//example.com',
      'javascript:alert(1)',
      '/projects/other/apis?focus=A',
      '/projects/p/unknown',
      '/projects/p/apis\\evil',
    ])
      expect(routeWorkspaceTab('p', href)).toBeNull()
    localStorage.setItem(
      'flowtest:workspace-tabs:v1:u:p',
      JSON.stringify(['apis', 'invalid', 'toString']),
    )
    expect(readWorkspaceTabs('u', 'p').tabs.map((tab) => tab.section)).toEqual(['apis'])
    localStorage.setItem(
      workspaceTabStorageKey('u', 'p'),
      JSON.stringify({
        schemaVersion: 2,
        tabs: [
          { href: '/projects/other/apis', label: 'foreign' },
          { href: '/projects/p/reports?execution=R', label: '冻结报告' },
        ],
      }),
    )
    expect(readWorkspaceTabs('u', 'p').tabs.map((tab) => tab.label)).toEqual(['冻结报告'])
    expect(readWorkspaceTabs('u', 'p').error).toContain('部分无效')
  })

  it('keeps storage failures explicit without deleting any resource draft', () => {
    localStorage.setItem('flowtest:api-draft:v1:u:A', 'resource-draft')
    const failure = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota')
    })
    expect(writeWorkspaceTabs('u', 'p', [])).toContain('仅保留在本次会话')
    expect(localStorage.getItem('flowtest:api-draft:v1:u:A')).toBe('resource-draft')
    failure.mockRestore()
  })
})
