import { QueryClient, QueryClientProvider, useQuery, type QueryKey } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, type RenderResult } from '@testing-library/react'
import { flushSync } from 'react-dom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useQueryInvalidated } from './use-query-invalidated'

type Authority = { capabilities: string[] }
type ReadAuthority = () => Promise<Authority>
const permissionKey = ['project-permissions', 'project-a'] as const
const memberKey = ['project-members', 'project-a'] as const

afterEach(() => vi.restoreAllMocks())

describe('useQueryInvalidated authority consumers', () => {
  it.each(['members', 'permission'] as const)(
    'recovers authority without updating its parent while the %s query child renders',
    async (child) => {
      const errors = vi.spyOn(console, 'error')
      const fixture = createAuthorityFixture()
      renderTree(
        fixture.client,
        <GovernanceWorkspace readAuthority={fixture.readAuthority} child={child} />,
      )
      expect(screen.getByText('保存治理')).toBeEnabled()

      fixture.failReads()
      await act(async () => {
        await fixture.client.invalidateQueries({ queryKey: permissionKey, exact: true })
      })
      await screen.findByText('权限重读失败')
      expect(screen.getByText('保存治理')).toBeDisabled()
      expect(screen.queryByText('附属读取已就绪')).not.toBeInTheDocument()

      fixture.allowReads()
      fireEvent.click(screen.getByText('重试权限'))
      await screen.findByText('附属读取已就绪')
      expect(screen.getByText('保存治理')).toBeEnabled()
      const crossRenderWarnings = errors.mock.calls.filter(([message]) =>
        String(message).includes('Cannot update a component'),
      )
      expect(crossRenderWarnings).toEqual([])
    },
  )

  it('closes the real write control synchronously when its authority is explicitly invalidated', () => {
    const fixture = createAuthorityFixture()
    renderTree(fixture.client, <GovernanceWorkspace readAuthority={fixture.readAuthority} />)
    expect(screen.getByText('保存治理')).toBeEnabled()

    act(() => {
      flushSync(() => {
        void fixture.client.invalidateQueries({
          queryKey: permissionKey,
          exact: true,
          refetchType: 'none',
        })
      })
      expect(screen.getByText('保存治理')).toBeDisabled()
    })
  })

  it('keeps a known authority writable during an ordinary stale background read', async () => {
    const fixture = createAuthorityFixture()
    fixture.client.setQueryData(permissionKey, { capabilities: ['edit'] }, { updatedAt: 1 })
    let release!: (authority: Authority) => void
    const pending = new Promise<Authority>((resolve) => {
      release = resolve
    })
    renderTree(fixture.client, <GovernanceWorkspace readAuthority={() => pending} />)
    try {
      await waitFor(() =>
        expect(fixture.client.getQueryState(permissionKey)?.fetchStatus).toBe('fetching'),
      )
      expect(fixture.client.getQueryState(permissionKey)?.isInvalidated).toBe(false)
      expect(screen.getByText('保存治理')).toBeEnabled()
      await act(async () => release({ capabilities: ['edit'] }))
      expect(screen.getByText('保存治理')).toBeEnabled()
    } finally {
      release({ capabilities: ['edit'] })
    }
  })

  it.each(['client', 'key'] as const)(
    'resolves the configured %s queryKeyHashFn without mixing other authority',
    (hashLocation) => {
      const hash = (key: QueryKey): string => `tenant-hash:${JSON.stringify(key)}`
      const client = new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            staleTime: 15_000,
            ...(hashLocation === 'client' ? { queryKeyHashFn: hash } : {}),
          },
        },
      })
      if (hashLocation === 'key')
        client.setQueryDefaults(['project-permissions'], { queryKeyHashFn: hash })
      client.setQueryData(permissionKey, { capabilities: ['edit'] })
      const otherKey = ['project-permissions', 'other-project'] as const
      client.setQueryData(otherKey, { capabilities: ['edit'] })
      renderTree(client, <InvalidationIndicator queryKey={permissionKey} />)

      act(() => {
        void client.invalidateQueries({ queryKey: otherKey, exact: true, refetchType: 'none' })
      })
      expect(screen.getByText('无显式失效')).toBeInTheDocument()
      act(() => {
        void client.invalidateQueries({ queryKey: permissionKey, exact: true, refetchType: 'none' })
      })
      expect(screen.getByText('等待权限确认')).toBeInTheDocument()
      act(() => client.setQueryData(permissionKey, { capabilities: ['read'] }))
      expect(screen.getByText('无显式失效')).toBeInTheDocument()
    },
  )

  it('follows removal and rebuilding of the same authority instead of the removed query object', () => {
    const fixture = createAuthorityFixture()
    renderTree(fixture.client, <InvalidationIndicator queryKey={permissionKey} />)
    act(() => {
      void fixture.client.invalidateQueries({
        queryKey: permissionKey,
        exact: true,
        refetchType: 'none',
      })
    })
    expect(screen.getByText('等待权限确认')).toBeInTheDocument()
    act(() => fixture.client.removeQueries({ queryKey: permissionKey, exact: true }))
    expect(screen.getByText('无显式失效')).toBeInTheDocument()
    act(() => fixture.client.setQueryData(permissionKey, { capabilities: ['read'] }))
    expect(screen.getByText('无显式失效')).toBeInTheDocument()
    act(() => {
      void fixture.client.invalidateQueries({
        queryKey: permissionKey,
        exact: true,
        refetchType: 'none',
      })
    })
    expect(screen.getByText('等待权限确认')).toBeInTheDocument()
    act(() => fixture.client.setQueryData(permissionKey, { capabilities: ['read'] }))
    expect(screen.getByText('无显式失效')).toBeInTheDocument()
  })

  it('switches authority keys without applying a previous scope notification to the new scope', () => {
    const fixture = createAuthorityFixture()
    const otherKey = ['project-permissions', 'project-b'] as const
    fixture.client.setQueryData(otherKey, { capabilities: ['read'] })
    act(() => {
      void fixture.client.invalidateQueries({
        queryKey: permissionKey,
        exact: true,
        refetchType: 'none',
      })
    })
    const view = renderTree(fixture.client, <InvalidationIndicator queryKey={permissionKey} />)
    expect(screen.getByText('等待权限确认')).toBeInTheDocument()
    view.rerender(
      <QueryClientProvider client={fixture.client}>
        <InvalidationIndicator queryKey={otherKey} />
      </QueryClientProvider>,
    )
    expect(screen.getByText('无显式失效')).toBeInTheDocument()
    act(() => fixture.client.setQueryData(permissionKey, { capabilities: ['edit'] }))
    expect(screen.getByText('无显式失效')).toBeInTheDocument()
    act(() => {
      void fixture.client.invalidateQueries({
        queryKey: otherKey,
        exact: true,
        refetchType: 'none',
      })
    })
    expect(screen.getByText('等待权限确认')).toBeInTheDocument()
    view.rerender(
      <QueryClientProvider client={fixture.client}>
        <InvalidationIndicator queryKey={permissionKey} />
      </QueryClientProvider>,
    )
    expect(screen.getByText('无显式失效')).toBeInTheDocument()
    act(() => fixture.client.removeQueries({ queryKey: otherKey, exact: true }))
    expect(screen.getByText('无显式失效')).toBeInTheDocument()
  })
})

function GovernanceWorkspace({
  readAuthority,
  child = 'members',
}: {
  readAuthority: ReadAuthority
  child?: 'members' | 'permission'
}) {
  const invalidated = useQueryInvalidated(permissionKey)
  const authority = useQuery({ queryKey: permissionKey, queryFn: readAuthority })
  const writable =
    !invalidated && authority.isSuccess && authority.data.capabilities.includes('edit')
  return (
    <>
      <button disabled={!writable}>保存治理</button>
      {authority.isError && <span>权限重读失败</span>}
      <button onClick={() => void authority.refetch()}>重试权限</button>
      {authority.isSuccess &&
        (child === 'members' ? (
          <MemberDirectory />
        ) : (
          <PermissionSummary readAuthority={readAuthority} />
        ))}
    </>
  )
}

function MemberDirectory() {
  const members = useQuery({ queryKey: memberKey, queryFn: async () => [] })
  return members.isSuccess ? <span>附属读取已就绪</span> : null
}

function PermissionSummary({ readAuthority }: { readAuthority: ReadAuthority }) {
  const authority = useQuery({ queryKey: permissionKey, queryFn: readAuthority })
  return authority.isSuccess ? <span>附属读取已就绪</span> : null
}

function InvalidationIndicator({ queryKey }: { queryKey: QueryKey }) {
  const invalidated = useQueryInvalidated(queryKey)
  return <span>{invalidated ? '等待权限确认' : '无显式失效'}</span>
}

function renderTree(client: QueryClient, children: ReactNode): RenderResult {
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>)
}

function createAuthorityFixture() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 15_000 } },
  })
  client.setQueryData(permissionKey, { capabilities: ['edit'] })
  client.setQueryData(memberKey, [])
  let fail = false
  const readAuthority: ReadAuthority = async () => {
    if (fail) throw new Error('权限重读失败')
    return { capabilities: ['edit'] }
  }
  return {
    client,
    readAuthority,
    failReads: () => {
      fail = true
    },
    allowReads: () => {
      fail = false
    },
  }
}
